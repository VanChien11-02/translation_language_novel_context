-- ============================================================================
-- ContextTranslate: patch schema v2 -> v3  (IDEMPOTENT: chạy lại nhiều lần được)
-- Chạy bằng:  python ctx.py init-db        (tool tự tách theo dòng "GO")
-- Hoặc dán vào SSMS. BACKUP DATABASE TRƯỚC KHI CHẠY.
-- Chưa được thử trên SQL Server thật trong môi trường soạn thảo: hãy chạy trên bản sao trước.
-- ============================================================================

------------------------------------------------------------------------------
-- 1. Characters
------------------------------------------------------------------------------
IF COL_LENGTH('dbo.Characters','Gender') IS NULL
    ALTER TABLE dbo.Characters ADD Gender VARCHAR(10) NULL;
IF COL_LENGTH('dbo.Characters','CharacterKind') IS NULL
    ALTER TABLE dbo.Characters ADD CharacterKind VARCHAR(12) NOT NULL
        CONSTRAINT DF_Characters_Kind DEFAULT 'person';
IF COL_LENGTH('dbo.Characters','DisplayNameVI') IS NULL
    ALTER TABLE dbo.Characters ADD DisplayNameVI NVARCHAR(120) NULL;
IF COL_LENGTH('dbo.Characters','ThirdPersonPronoun') IS NULL
    ALTER TABLE dbo.Characters ADD ThirdPersonPronoun NVARCHAR(40) NULL;
IF COL_LENGTH('dbo.Characters','SpeechStyle') IS NULL
    ALTER TABLE dbo.Characters ADD SpeechStyle NVARCHAR(500) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_Characters_Kind')
    ALTER TABLE dbo.Characters ADD CONSTRAINT CK_Characters_Kind
        CHECK (CharacterKind IN ('person','narrator','group','system'));
GO

------------------------------------------------------------------------------
-- 2. StoryEvents
------------------------------------------------------------------------------
IF COL_LENGTH('dbo.StoryEvents','ChapterNumber') IS NULL
    ALTER TABLE dbo.StoryEvents ADD ChapterNumber INT NULL;
IF COL_LENGTH('dbo.StoryEvents','ParaIndex') IS NULL
    ALTER TABLE dbo.StoryEvents ADD ParaIndex INT NULL;
IF COL_LENGTH('dbo.StoryEvents','AffectsPronouns') IS NULL
    ALTER TABLE dbo.StoryEvents ADD AffectsPronouns BIT NOT NULL
        CONSTRAINT DF_StoryEvents_AP DEFAULT 0;
GO
UPDATE e SET e.ChapterNumber = c.ChapterNumber
FROM dbo.StoryEvents e JOIN dbo.Chapters c ON c.ChapterId = e.ChapterId
WHERE e.ChapterNumber IS NULL;
GO
-- ChunkIndex cũ có thể NOT NULL; sự kiện sinh tự động neo theo ParaIndex nên cho phép NULL
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.StoryEvents')
           AND name = 'ChunkIndex' AND is_nullable = 0)
    ALTER TABLE dbo.StoryEvents ALTER COLUMN ChunkIndex INT NULL;
GO

------------------------------------------------------------------------------
-- 3. PronounRules
------------------------------------------------------------------------------
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.PronounRules')
           AND name = 'ListenerId' AND is_nullable = 0)
    ALTER TABLE dbo.PronounRules ALTER COLUMN ListenerId INT NULL;
GO
IF COL_LENGTH('dbo.PronounRules','SpeechMode') IS NULL
    ALTER TABLE dbo.PronounRules ADD SpeechMode VARCHAR(10) NOT NULL
        CONSTRAINT DF_PR_Mode DEFAULT 'speech';
IF COL_LENGTH('dbo.PronounRules','ReferPronoun') IS NULL
    ALTER TABLE dbo.PronounRules ADD ReferPronoun NVARCHAR(60) NULL;
IF COL_LENGTH('dbo.PronounRules','StartChapter') IS NULL
    ALTER TABLE dbo.PronounRules ADD StartChapter INT NOT NULL CONSTRAINT DF_PR_SC DEFAULT 0;
IF COL_LENGTH('dbo.PronounRules','StartPara') IS NULL
    ALTER TABLE dbo.PronounRules ADD StartPara INT NOT NULL CONSTRAINT DF_PR_SP DEFAULT 0;
IF COL_LENGTH('dbo.PronounRules','EndChapter') IS NULL
    ALTER TABLE dbo.PronounRules ADD EndChapter INT NULL;
IF COL_LENGTH('dbo.PronounRules','EndPara') IS NULL
    ALTER TABLE dbo.PronounRules ADD EndPara INT NULL;
IF COL_LENGTH('dbo.PronounRules','EventId') IS NULL
    ALTER TABLE dbo.PronounRules ADD EventId BIGINT NULL;
GO
IF COL_LENGTH('dbo.PronounRules','StartPos') IS NULL
    ALTER TABLE dbo.PronounRules ADD StartPos AS (StartChapter * 100000 + StartPara) PERSISTED;
IF COL_LENGTH('dbo.PronounRules','EndPos') IS NULL
    ALTER TABLE dbo.PronounRules ADD EndPos AS
        (CASE WHEN EndChapter IS NULL THEN NULL ELSE EndChapter * 100000 + ISNULL(EndPara, 0) END) PERSISTED;
GO
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_PR_Mode')
    ALTER TABLE dbo.PronounRules ADD CONSTRAINT CK_PR_Mode
        CHECK (SpeechMode IN ('speech','thought','narration'));
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_PR_Range')
    ALTER TABLE dbo.PronounRules ADD CONSTRAINT CK_PR_Range
        CHECK (EndPos IS NULL OR EndPos > StartPos);
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_PR_Event')
    ALTER TABLE dbo.PronounRules ADD CONSTRAINT FK_PR_Event
        FOREIGN KEY (EventId) REFERENCES dbo.StoryEvents(EventId);
GO
-- CHẨN ĐOÁN: nếu schema v2 đã có UNIQUE trên (BookId, SpeakerId, ListenerId, SceneState) thì nó sẽ chặn
-- các rule theo mode / khoảng thời gian. Xem các index unique hiện có:
--   SELECT i.name, i.is_unique_constraint, STRING_AGG(c.name, ',') cols
--   FROM sys.indexes i JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id
--   JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id
--   WHERE i.object_id=OBJECT_ID('dbo.PronounRules') AND i.is_unique=1 GROUP BY i.name, i.is_unique_constraint;
-- rồi DROP index/constraint cũ trước khi tạo index mới dưới đây.
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_PronounRules_Active'
               AND object_id = OBJECT_ID('dbo.PronounRules'))
    CREATE UNIQUE INDEX UX_PronounRules_Active
        ON dbo.PronounRules (BookId, SpeakerId, ListenerId, SpeechMode, SceneState, StartPos)
        WHERE IsConfirmed = 1;
GO

------------------------------------------------------------------------------
-- 4. ContextFacts: From/Until -> Start/End (End không bao gồm), vị trí theo ĐOẠN
------------------------------------------------------------------------------
IF COL_LENGTH('dbo.ContextFacts','FromChapter') IS NOT NULL AND COL_LENGTH('dbo.ContextFacts','StartChapter') IS NULL
    EXEC sp_rename 'dbo.ContextFacts.FromChapter', 'StartChapter', 'COLUMN';
IF COL_LENGTH('dbo.ContextFacts','FromChunk') IS NOT NULL AND COL_LENGTH('dbo.ContextFacts','StartPara') IS NULL
    EXEC sp_rename 'dbo.ContextFacts.FromChunk', 'StartPara', 'COLUMN';
IF COL_LENGTH('dbo.ContextFacts','UntilChapter') IS NOT NULL AND COL_LENGTH('dbo.ContextFacts','EndChapter') IS NULL
    EXEC sp_rename 'dbo.ContextFacts.UntilChapter', 'EndChapter', 'COLUMN';
IF COL_LENGTH('dbo.ContextFacts','UntilChunk') IS NOT NULL AND COL_LENGTH('dbo.ContextFacts','EndPara') IS NULL
    EXEC sp_rename 'dbo.ContextFacts.UntilChunk', 'EndPara', 'COLUMN';
GO
UPDATE dbo.ContextFacts SET StartChapter = ISNULL(StartChapter, 0), StartPara = ISNULL(StartPara, 0);
GO
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.ContextFacts')
           AND name = 'StartChapter' AND is_nullable = 1)
    ALTER TABLE dbo.ContextFacts ALTER COLUMN StartChapter INT NOT NULL;
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.ContextFacts')
           AND name = 'StartPara' AND is_nullable = 1)
    ALTER TABLE dbo.ContextFacts ALTER COLUMN StartPara INT NOT NULL;
GO
IF COL_LENGTH('dbo.ContextFacts','StartPos') IS NULL
    ALTER TABLE dbo.ContextFacts ADD StartPos AS (StartChapter * 100000 + StartPara) PERSISTED;
IF COL_LENGTH('dbo.ContextFacts','EndPos') IS NULL
    ALTER TABLE dbo.ContextFacts ADD EndPos AS
        (CASE WHEN EndChapter IS NULL THEN NULL ELSE EndChapter * 100000 + ISNULL(EndPara, 0) END) PERSISTED;
GO

------------------------------------------------------------------------------
-- 5. CharacterRelationships
------------------------------------------------------------------------------
IF COL_LENGTH('dbo.CharacterRelationships','StartChapterNumber') IS NOT NULL
   AND COL_LENGTH('dbo.CharacterRelationships','StartChapter') IS NULL
    EXEC sp_rename 'dbo.CharacterRelationships.StartChapterNumber', 'StartChapter', 'COLUMN';
IF COL_LENGTH('dbo.CharacterRelationships','EndChapterNumber') IS NOT NULL
   AND COL_LENGTH('dbo.CharacterRelationships','EndChapter') IS NULL
    EXEC sp_rename 'dbo.CharacterRelationships.EndChapterNumber', 'EndChapter', 'COLUMN';
GO
IF COL_LENGTH('dbo.CharacterRelationships','StartPara') IS NULL
    ALTER TABLE dbo.CharacterRelationships ADD StartPara INT NOT NULL CONSTRAINT DF_CR_SP DEFAULT 0;
IF COL_LENGTH('dbo.CharacterRelationships','EndPara') IS NULL
    ALTER TABLE dbo.CharacterRelationships ADD EndPara INT NULL;
GO

------------------------------------------------------------------------------
-- 6. GlossaryTerms
------------------------------------------------------------------------------
IF COL_LENGTH('dbo.GlossaryTerms','Variants') IS NULL
    ALTER TABLE dbo.GlossaryTerms ADD Variants NVARCHAR(500) NULL;
IF COL_LENGTH('dbo.GlossaryTerms','DoNotTranslate') IS NULL
    ALTER TABLE dbo.GlossaryTerms ADD DoNotTranslate BIT NOT NULL CONSTRAINT DF_GT_DNT DEFAULT 0;
IF COL_LENGTH('dbo.GlossaryTerms','FirstSeenChapter') IS NULL
    ALTER TABLE dbo.GlossaryTerms ADD FirstSeenChapter INT NULL;
GO

------------------------------------------------------------------------------
-- 7. Bảng mới
------------------------------------------------------------------------------
IF OBJECT_ID('dbo.ChapterScenes') IS NULL
CREATE TABLE dbo.ChapterScenes (
    SceneId       INT IDENTITY(1,1) PRIMARY KEY,
    BookId        INT NOT NULL REFERENCES dbo.Books(BookId),
    ChapterId     INT NOT NULL REFERENCES dbo.Chapters(ChapterId),
    SceneIndex    INT NOT NULL,
    StartPara     INT NOT NULL,                 -- bao gồm
    EndPara       INT NULL,                     -- không bao gồm; NULL = hết chương
    Location      NVARCHAR(200)  NULL,
    TimeOfDay     NVARCHAR(100)  NULL,
    Mood          NVARCHAR(200)  NULL,
    SummaryVI     NVARCHAR(1000) NULL,
    ReviewStatus  VARCHAR(20)    NOT NULL DEFAULT 'suggested'
                  CHECK (ReviewStatus IN ('suggested','confirmed','rejected','unknown')),
    CreatedAt     DATETIME2(0)   NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT UQ_ChapterScenes UNIQUE (ChapterId, SceneIndex)
);
GO
IF OBJECT_ID('dbo.ModelVersions') IS NULL
CREATE TABLE dbo.ModelVersions (
    ModelVersionId  INT IDENTITY(1,1) PRIMARY KEY,
    BaseModel       NVARCHAR(100) NOT NULL,
    AdapterPath     NVARCHAR(400) NULL,
    TemplateVersion VARCHAR(20)   NOT NULL,
    TrainSetHash    CHAR(64)      NULL,
    TrainExamples   INT           NULL,
    Hyperparams     NVARCHAR(MAX) NULL,
    EvalResult      NVARCHAR(MAX) NULL,
    IsActive        BIT           NOT NULL DEFAULT 0,
    CreatedAt       DATETIME2(0)  NOT NULL DEFAULT SYSUTCDATETIME()
);
GO
IF OBJECT_ID('dbo.TranslationJobs') IS NULL
CREATE TABLE dbo.TranslationJobs (
    JobId           INT IDENTITY(1,1) PRIMARY KEY,
    BookId          INT NOT NULL REFERENCES dbo.Books(BookId),
    ChapterId       INT NOT NULL REFERENCES dbo.Chapters(ChapterId),
    ModelVersionId  INT NULL REFERENCES dbo.ModelVersions(ModelVersionId),
    TemplateVersion VARCHAR(20) NOT NULL,
    JobStatus       VARCHAR(20) NOT NULL DEFAULT 'exported'
                    CHECK (JobStatus IN ('exported','running','imported','partial','failed')),
    PendingFile     NVARCHAR(260) NULL,
    ResultFile      NVARCHAR(260) NULL,
    ChunkCount      INT NULL,
    FailedCount     INT NULL,
    Notes           NVARCHAR(500) NULL,
    ExportedAt      DATETIME2(0) NOT NULL DEFAULT SYSUTCDATETIME(),
    ImportedAt      DATETIME2(0) NULL
);
GO
IF OBJECT_ID('dbo.TranslationContextSnapshots') IS NULL
CREATE TABLE dbo.TranslationContextSnapshots (
    SnapshotId      BIGINT IDENTITY(1,1) PRIMARY KEY,
    BookId          INT NOT NULL REFERENCES dbo.Books(BookId),
    ChapterNumber   INT NOT NULL,
    ParaStart       INT NOT NULL,
    ParaEnd         INT NOT NULL,
    TemplateVersion VARCHAR(20) NOT NULL,
    ContextHash     CHAR(64)    NOT NULL,
    ContextJson     NVARCHAR(MAX) NOT NULL,
    CreatedAt       DATETIME2(0) NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT UQ_Snapshot UNIQUE (BookId, ChapterNumber, ParaStart, ParaEnd, ContextHash)
);
GO
-- Lưu nhãn TỪNG ĐOẠN (kết quả Stage 1.5). Nguồn để dựng chunk, context và file train.
IF OBJECT_ID('dbo.ChapterParagraphs') IS NULL
CREATE TABLE dbo.ChapterParagraphs (
    ParagraphId   BIGINT IDENTITY(1,1) PRIMARY KEY,
    BookId        INT NOT NULL REFERENCES dbo.Books(BookId),
    ChapterId     INT NOT NULL REFERENCES dbo.Chapters(ChapterId),
    ChapterNumber INT NOT NULL,
    ParaIndex     INT NOT NULL,                 -- 1-based trong bản gốc đã làm sạch
    Pos           AS (ChapterNumber * 100000 + ParaIndex) PERSISTED,
    SourceEN      NVARCHAR(MAX) NOT NULL,
    TargetVI      NVARCHAR(MAX) NULL,
    SourceHash    CHAR(64)      NOT NULL,
    Mode          VARCHAR(10)   NOT NULL
                  CHECK (Mode IN ('speech','thought','narration','system','sfx')),
    SpeakerId     INT NULL REFERENCES dbo.Characters(CharacterId),
    ListenerId    INT NULL REFERENCES dbo.Characters(CharacterId),
    SceneState    NVARCHAR(40)  NULL,
    SceneBreak    BIT           NOT NULL DEFAULT 0,   -- đoạn này mở đầu một cảnh mới
    IsConfirmed   BIT           NOT NULL DEFAULT 0,
    AlignConf     VARCHAR(8)    NULL,
    Flags         NVARCHAR(400) NULL,
    Note          NVARCHAR(500) NULL,
    UpdatedAt     DATETIME2(0)  NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT UQ_ChapterParagraphs UNIQUE (BookId, ChapterNumber, ParaIndex)
);
GO

------------------------------------------------------------------------------
-- 8. TranslationChunks / TranslationExamples (cột bổ sung theo spec v3)
------------------------------------------------------------------------------
IF COL_LENGTH('dbo.TranslationChunks','ParaStart') IS NULL
    ALTER TABLE dbo.TranslationChunks ADD ParaStart INT NULL;
IF COL_LENGTH('dbo.TranslationChunks','ParaEnd') IS NULL
    ALTER TABLE dbo.TranslationChunks ADD ParaEnd INT NULL;
IF COL_LENGTH('dbo.TranslationChunks','TemplateVersion') IS NULL
    ALTER TABLE dbo.TranslationChunks ADD TemplateVersion VARCHAR(20) NULL;
IF COL_LENGTH('dbo.TranslationChunks','SnapshotId') IS NULL
    ALTER TABLE dbo.TranslationChunks ADD SnapshotId BIGINT NULL;
IF COL_LENGTH('dbo.TranslationChunks','ModelVersionId') IS NULL
    ALTER TABLE dbo.TranslationChunks ADD ModelVersionId INT NULL;
IF COL_LENGTH('dbo.TranslationChunks','QaFlags') IS NULL
    ALTER TABLE dbo.TranslationChunks ADD QaFlags VARCHAR(200) NULL;
GO
IF COL_LENGTH('dbo.TranslationExamples','Granularity') IS NULL
    ALTER TABLE dbo.TranslationExamples ADD Granularity VARCHAR(10) NOT NULL CONSTRAINT DF_TE_Gran DEFAULT 'line';
IF COL_LENGTH('dbo.TranslationExamples','ChapterId') IS NULL
    ALTER TABLE dbo.TranslationExamples ADD ChapterId INT NULL;
IF COL_LENGTH('dbo.TranslationExamples','ChunkIndex') IS NULL
    ALTER TABLE dbo.TranslationExamples ADD ChunkIndex INT NULL;
IF COL_LENGTH('dbo.TranslationExamples','SnapshotId') IS NULL
    ALTER TABLE dbo.TranslationExamples ADD SnapshotId BIGINT NULL;
IF COL_LENGTH('dbo.TranslationExamples','Split') IS NULL
    ALTER TABLE dbo.TranslationExamples ADD Split VARCHAR(5) NOT NULL CONSTRAINT DF_TE_Split DEFAULT 'train';
IF COL_LENGTH('dbo.TranslationExamples','TemplateVersion') IS NULL
    ALTER TABLE dbo.TranslationExamples ADD TemplateVersion VARCHAR(20) NULL;
GO

-- ============================================================================
-- ContextTranslate - SCHEMA ĐẦY ĐỦ v3 (tạo mới từ đầu). 18 bảng nghiệp vụ (+ SchemaInfo) + 3 view + 1 trigger.
--
-- * Chạy trong DATABASE ĐÃ CHỌN (xem 010_create_database.sql). Yêu cầu SQL Server 2016 SP1+.
-- * IDEMPOTENT: bảng/chỉ mục đã tồn tại thì bỏ qua (KHÔNG sửa bảng cũ; muốn nâng cấp DB v2 hãy dùng 001_patch_v3.sql).
-- * Quy ước: ReviewStatus ∈ suggested/confirmed/rejected/unknown; End của mọi khoảng KHÔNG bao gồm;
--   vị trí chuẩn Pos = ChapterNumber*100000 + ParaIndex (đoạn văn 1-based trong bản gốc đã làm sạch).
-- * Cùng-BookId được ép bằng khoá ngoại ghép (CharacterId, BookId) / (ChapterId, BookId) / (EventId, BookId).
-- * CHƯA được chạy thử trên SQL Server thật trong môi trường soạn thảo: hãy chạy trên DB trống/bản sao trước.
-- ============================================================================
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
SET ANSI_PADDING ON;
SET ANSI_WARNINGS ON;
SET ARITHABORT ON;
SET CONCAT_NULL_YIELDS_NULL ON;
SET NUMERIC_ROUNDABORT OFF;
GO

------------------------------------------------------------------------------
-- 0. Thông tin phiên bản schema
------------------------------------------------------------------------------
IF OBJECT_ID('dbo.SchemaInfo','U') IS NULL
CREATE TABLE dbo.SchemaInfo (
    SchemaVersion VARCHAR(20)  NOT NULL CONSTRAINT PK_SchemaInfo PRIMARY KEY,
    AppliedAt     DATETIME2(0) NOT NULL CONSTRAINT DF_SchemaInfo_AppliedAt DEFAULT SYSUTCDATETIME(),
    Notes         NVARCHAR(200) NULL
);
GO

------------------------------------------------------------------------------
-- 1. Books
------------------------------------------------------------------------------
IF OBJECT_ID('dbo.Books','U') IS NULL
CREATE TABLE dbo.Books (
    BookId           INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Books PRIMARY KEY,
    BookKey          NVARCHAR(120)  NOT NULL CONSTRAINT UQ_Books_BookKey UNIQUE,
    Title            NVARCHAR(250)  NOT NULL,
    Genre            NVARCHAR(120)  NULL,
    StyleGuide       NVARCHAR(MAX)  NULL,      -- ngắn gọn (<= ~600 ký tự): nằm trong MỌI prompt
    CreatedAt        DATETIME2(0)   NOT NULL CONSTRAINT DF_Books_CreatedAt DEFAULT SYSUTCDATETIME(),
    OriginalLanguage VARCHAR(10)    NOT NULL CONSTRAINT DF_Books_OrigLang DEFAULT 'en',
    TargetLanguage   VARCHAR(10)    NOT NULL CONSTRAINT DF_Books_TgtLang DEFAULT 'vi',
    AuthorName       NVARCHAR(200)  NULL,
    BookStatus       VARCHAR(20)    NOT NULL CONSTRAINT DF_Books_Status DEFAULT 'reading',
    UpdatedAt        DATETIME2(0)   NULL,
    CONSTRAINT CK_Books_Status CHECK (BookStatus IN ('new','reading','completed','paused'))
);
GO

------------------------------------------------------------------------------
-- 2. Chapters
------------------------------------------------------------------------------
IF OBJECT_ID('dbo.Chapters','U') IS NULL
CREATE TABLE dbo.Chapters (
    ChapterId      INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Chapters PRIMARY KEY,
    BookId         INT NOT NULL CONSTRAINT FK_Chapters_Books REFERENCES dbo.Books(BookId),
    ChapterNumber  INT NOT NULL,                           -- prologue có thể = 0
    Title          NVARCHAR(250) NULL,
    SummaryVI      NVARCHAR(MAX) NULL,                     -- chỉ dựa trên nội dung ĐÃ ĐỌC (tránh spoiler)
    CreatedAt      DATETIME2(0)  NOT NULL CONSTRAINT DF_Chapters_CreatedAt DEFAULT SYSUTCDATETIME(),
    SourceFileName NVARCHAR(260) NULL,
    ChapterStatus  VARCHAR(20)   NOT NULL CONSTRAINT DF_Chapters_Status DEFAULT 'new',
    TranslatedAt   DATETIME2(0)  NULL,
    UpdatedAt      DATETIME2(0)  NOT NULL CONSTRAINT DF_Chapters_UpdatedAt DEFAULT SYSUTCDATETIME(),
    CONSTRAINT CK_Chapters_Status CHECK (ChapterStatus IN
        ('new','annotated','translating','translated','reviewed','completed')),
    CONSTRAINT UQ_Chapters_BookNumber UNIQUE (BookId, ChapterNumber),
    CONSTRAINT UQ_Chapters_IdBook     UNIQUE (ChapterId, BookId)
);
GO

------------------------------------------------------------------------------
-- 3. Characters  (gồm nhân vật 'narrator' và các nhóm 'group' như "Arona, Plana")
------------------------------------------------------------------------------
IF OBJECT_ID('dbo.Characters','U') IS NULL
CREATE TABLE dbo.Characters (
    CharacterId        INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Characters PRIMARY KEY,
    BookId             INT NOT NULL CONSTRAINT FK_Characters_Books REFERENCES dbo.Books(BookId),
    Name               NVARCHAR(120) NOT NULL,
    Notes              NVARCHAR(MAX) NULL,
    Description        NVARCHAR(MAX) NULL,                  -- ổn định, không spoiler
    FirstSeenChapter   INT NULL,
    ReviewStatus       VARCHAR(20)   NOT NULL CONSTRAINT DF_Characters_Review DEFAULT 'suggested',
    CreatedAt          DATETIME2(0)  NOT NULL CONSTRAINT DF_Characters_CreatedAt DEFAULT SYSUTCDATETIME(),
    Gender             VARCHAR(10)   NULL,                  -- male / female / other / unknown
    CharacterKind      VARCHAR(12)   NOT NULL CONSTRAINT DF_Characters_Kind DEFAULT 'person',
    DisplayNameVI      NVARCHAR(120) NULL,                  -- tên hiển thị trong bản dịch
    ThirdPersonPronoun NVARCHAR(40)  NULL,                  -- người dẫn truyện gọi: "anh / anh ta"
    SpeechStyle        NVARCHAR(500) NULL,                  -- giọng nói
    CONSTRAINT CK_Characters_Review CHECK (ReviewStatus IN ('suggested','confirmed','rejected','unknown')),
    CONSTRAINT CK_Characters_Gender CHECK (Gender IS NULL OR Gender IN ('male','female','other','unknown')),
    CONSTRAINT CK_Characters_Kind   CHECK (CharacterKind IN ('person','narrator','group','system')),
    CONSTRAINT UQ_Characters_BookName UNIQUE (BookId, Name),
    CONSTRAINT UQ_Characters_IdBook   UNIQUE (CharacterId, BookId)
);
GO

------------------------------------------------------------------------------
-- 4. CharacterAliases
------------------------------------------------------------------------------
IF OBJECT_ID('dbo.CharacterAliases','U') IS NULL
CREATE TABLE dbo.CharacterAliases (
    AliasId      INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_CharacterAliases PRIMARY KEY,
    CharacterId  INT NOT NULL CONSTRAINT FK_Aliases_Characters REFERENCES dbo.Characters(CharacterId),
    AliasName    NVARCHAR(150) NOT NULL,
    AliasType    VARCHAR(25)   NULL,                        -- nickname / title / name_variant
    IsConfirmed  BIT NOT NULL CONSTRAINT DF_Aliases_Confirmed DEFAULT 0,
    CONSTRAINT UQ_Aliases UNIQUE (CharacterId, AliasName)
);
GO

------------------------------------------------------------------------------
-- 5. CharacterRelationships  (A -> B, có hướng, có khoảng hiệu lực)
------------------------------------------------------------------------------
IF OBJECT_ID('dbo.CharacterRelationships','U') IS NULL
CREATE TABLE dbo.CharacterRelationships (
    RelationshipId   INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_CharacterRelationships PRIMARY KEY,
    BookId           INT NOT NULL,
    CharacterAId     INT NOT NULL,
    CharacterBId     INT NOT NULL,
    RelationshipType NVARCHAR(70) NOT NULL,                 -- teacher_student / siblings / enemy / ally
    Description      NVARCHAR(MAX) NULL,
    StartChapter     INT NULL,
    StartPara        INT NOT NULL CONSTRAINT DF_CR_StartPara DEFAULT 0,
    EndChapter       INT NULL,                              -- không bao gồm
    EndPara          INT NULL,
    ReviewStatus     VARCHAR(20) NOT NULL CONSTRAINT DF_CR_Review DEFAULT 'suggested',
    CONSTRAINT CK_CR_Review CHECK (ReviewStatus IN ('suggested','confirmed','rejected','unknown')),
    CONSTRAINT CK_CR_Distinct CHECK (CharacterAId <> CharacterBId),
    CONSTRAINT FK_CR_Book FOREIGN KEY (BookId) REFERENCES dbo.Books(BookId),
    CONSTRAINT FK_CR_A FOREIGN KEY (CharacterAId, BookId) REFERENCES dbo.Characters(CharacterId, BookId),
    CONSTRAINT FK_CR_B FOREIGN KEY (CharacterBId, BookId) REFERENCES dbo.Characters(CharacterId, BookId)
);
GO

------------------------------------------------------------------------------
-- 6. StoryEvents  (sự kiện đổi trạng thái / xưng hô; tự sinh từ nhãn bằng ctx.py build-context)
------------------------------------------------------------------------------
IF OBJECT_ID('dbo.StoryEvents','U') IS NULL
CREATE TABLE dbo.StoryEvents (
    EventId         BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_StoryEvents PRIMARY KEY,
    BookId          INT NOT NULL,
    ChapterId       INT NOT NULL,
    ChapterNumber   INT NULL,                               -- sao chép từ Chapters để tính Pos
    ParaIndex       INT NULL,                               -- đoạn xảy ra sự kiện (1-based)
    ChunkIndex      INT NULL,                               -- tương thích schema cũ
    EventType       VARCHAR(50)   NOT NULL,                 -- pronoun_shift / curse_removed / betrayal ...
    EventTitle      NVARCHAR(250) NOT NULL,
    DescriptionVI   NVARCHAR(MAX) NULL,
    EvidenceEN      NVARCHAR(MAX) NULL,
    DetectionMethod VARCHAR(25)   NOT NULL CONSTRAINT DF_SE_Method DEFAULT 'manual',   -- manual / ai / label_diff
    ReviewStatus    VARCHAR(20)   NOT NULL CONSTRAINT DF_SE_Review DEFAULT 'suggested',
    CreatedAt       DATETIME2(0)  NOT NULL CONSTRAINT DF_SE_CreatedAt DEFAULT SYSUTCDATETIME(),
    AffectsPronouns BIT NOT NULL CONSTRAINT DF_SE_AP DEFAULT 0,
    CONSTRAINT CK_SE_Review CHECK (ReviewStatus IN ('suggested','confirmed','rejected','unknown')),
    CONSTRAINT FK_SE_Book    FOREIGN KEY (BookId) REFERENCES dbo.Books(BookId),
    CONSTRAINT FK_SE_Chapter FOREIGN KEY (ChapterId, BookId) REFERENCES dbo.Chapters(ChapterId, BookId),
    CONSTRAINT UQ_SE_IdBook  UNIQUE (EventId, BookId)
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_StoryEvents_Anchor'
               AND object_id = OBJECT_ID('dbo.StoryEvents'))
    CREATE UNIQUE INDEX UX_StoryEvents_Anchor
        ON dbo.StoryEvents (BookId, ChapterId, ParaIndex, EventType) WHERE ParaIndex IS NOT NULL;
GO

------------------------------------------------------------------------------
-- 7. StoryEventCharacters
------------------------------------------------------------------------------
IF OBJECT_ID('dbo.StoryEventCharacters','U') IS NULL
CREATE TABLE dbo.StoryEventCharacters (
    EventId      BIGINT NOT NULL,
    BookId       INT    NOT NULL,
    CharacterId  INT    NOT NULL,
    EffectState  NVARCHAR(70) NULL,                         -- normal / cursed / hostile ...
    Notes        NVARCHAR(500) NULL,
    CONSTRAINT PK_StoryEventCharacters PRIMARY KEY (EventId, CharacterId),
    CONSTRAINT FK_SEC_Event FOREIGN KEY (EventId, BookId) REFERENCES dbo.StoryEvents(EventId, BookId),
    CONSTRAINT FK_SEC_Char  FOREIGN KEY (CharacterId, BookId) REFERENCES dbo.Characters(CharacterId, BookId)
);
GO

------------------------------------------------------------------------------
-- 8. PronounRules
--    Khoá = (Speaker, Listener, SpeechMode, SceneState). SceneState '*' = mặc định cho mọi trạng thái;
--    dòng có state cụ thể là NGOẠI LỆ ghi đè. ListenerId NULL = độc thoại / không rõ người nghe.
--    Rule đổi theo thời gian: Start/End (chương, đoạn); End không bao gồm.
------------------------------------------------------------------------------
IF OBJECT_ID('dbo.PronounRules','U') IS NULL
CREATE TABLE dbo.PronounRules (
    RuleId         INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_PronounRules PRIMARY KEY,
    BookId         INT NOT NULL,
    SpeakerId      INT NOT NULL,
    ListenerId     INT NULL,
    SpeechMode     VARCHAR(10)   NOT NULL CONSTRAINT DF_PR_Mode DEFAULT 'speech',   -- speech / thought / narration
    SceneState     NVARCHAR(40)  NOT NULL CONSTRAINT DF_PR_State DEFAULT '*',
    SelfPronoun    NVARCHAR(60)  NULL,
    AddressPronoun NVARCHAR(60)  NULL,
    ReferPronoun   NVARCHAR(60)  NULL,                      -- ngôi 3 khi nhắc tới người nghe: "anh ta"
    Notes          NVARCHAR(500) NULL,
    IsConfirmed    BIT NOT NULL CONSTRAINT DF_PR_Confirmed DEFAULT 0,
    Priority       SMALLINT NOT NULL CONSTRAINT DF_PR_Priority DEFAULT 0,
    StartChapter   INT NOT NULL CONSTRAINT DF_PR_SC DEFAULT 0,
    StartPara      INT NOT NULL CONSTRAINT DF_PR_SP DEFAULT 0,
    EndChapter     INT NULL,
    EndPara        INT NULL,
    EventId        BIGINT NULL,
    StartPos AS (StartChapter * 100000 + StartPara) PERSISTED,
    EndPos   AS (CASE WHEN EndChapter IS NULL THEN NULL
                      ELSE EndChapter * 100000 + ISNULL(EndPara, 0) END) PERSISTED,
    CONSTRAINT CK_PR_Mode  CHECK (SpeechMode IN ('speech','thought','narration')),
    CONSTRAINT CK_PR_Range CHECK (EndPos IS NULL OR EndPos > StartPos),
    CONSTRAINT FK_PR_Book     FOREIGN KEY (BookId) REFERENCES dbo.Books(BookId),
    CONSTRAINT FK_PR_Speaker  FOREIGN KEY (SpeakerId, BookId)  REFERENCES dbo.Characters(CharacterId, BookId),
    CONSTRAINT FK_PR_Listener FOREIGN KEY (ListenerId, BookId) REFERENCES dbo.Characters(CharacterId, BookId),
    CONSTRAINT FK_PR_Event    FOREIGN KEY (EventId, BookId)    REFERENCES dbo.StoryEvents(EventId, BookId)
);
GO
-- Một rule ĐÃ DUYỆT cho mỗi (cặp, mode, state, điểm bắt đầu)
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_PronounRules_Active'
               AND object_id = OBJECT_ID('dbo.PronounRules'))
    CREATE UNIQUE INDEX UX_PronounRules_Active
        ON dbo.PronounRules (BookId, SpeakerId, ListenerId, SpeechMode, SceneState, StartPos)
        WHERE IsConfirmed = 1;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_PronounRules_Lookup'
               AND object_id = OBJECT_ID('dbo.PronounRules'))
    CREATE INDEX IX_PronounRules_Lookup ON dbo.PronounRules (BookId, SpeakerId, SpeechMode)
        WHERE IsConfirmed = 1;
GO
-- Không cho hai rule ĐÃ DUYỆT cùng khoá chồng khoảng hiệu lực (CHECK từng dòng không làm được)
CREATE OR ALTER TRIGGER dbo.TR_PronounRules_NoOverlap ON dbo.PronounRules
AFTER INSERT, UPDATE AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1
        FROM inserted i
        JOIN dbo.PronounRules r
          ON r.RuleId <> i.RuleId
         AND r.IsConfirmed = 1 AND i.IsConfirmed = 1
         AND r.BookId = i.BookId
         AND r.SpeakerId = i.SpeakerId
         AND ISNULL(r.ListenerId, -1) = ISNULL(i.ListenerId, -1)
         AND r.SpeechMode = i.SpeechMode
         AND r.SceneState = i.SceneState
         AND r.StartPos < ISNULL(i.EndPos, 2147483647)
         AND i.StartPos < ISNULL(r.EndPos, 2147483647)
    )
    BEGIN
        ROLLBACK TRANSACTION;
        THROW 50001, N'PronounRules: hai quy tắc đã duyệt cùng khoá bị chồng khoảng hiệu lực.', 1;
    END
END;
GO

------------------------------------------------------------------------------
-- 9. ContextFacts  (sự thật có hiệu lực theo thời gian)
------------------------------------------------------------------------------
IF OBJECT_ID('dbo.ContextFacts','U') IS NULL
CREATE TABLE dbo.ContextFacts (
    FactId       BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_ContextFacts PRIMARY KEY,
    BookId       INT NOT NULL,
    CharacterId  INT NULL,                                  -- NULL = toàn truyện
    FactType     VARCHAR(50)   NOT NULL,                    -- identity / mind_state / location / loyalty
    FactText     NVARCHAR(MAX) NOT NULL,
    StartChapter INT NOT NULL CONSTRAINT DF_CF_SC DEFAULT 0,
    StartPara    INT NOT NULL CONSTRAINT DF_CF_SP DEFAULT 0,
    EndChapter   INT NULL,                                  -- không bao gồm
    EndPara      INT NULL,
    EvidenceEN   NVARCHAR(MAX) NULL,
    ReviewStatus VARCHAR(20)   NOT NULL CONSTRAINT DF_CF_Review DEFAULT 'suggested',
    CreatedAt    DATETIME2(0)  NOT NULL CONSTRAINT DF_CF_CreatedAt DEFAULT SYSUTCDATETIME(),
    StartPos AS (StartChapter * 100000 + StartPara) PERSISTED,
    EndPos   AS (CASE WHEN EndChapter IS NULL THEN NULL
                      ELSE EndChapter * 100000 + ISNULL(EndPara, 0) END) PERSISTED,
    CONSTRAINT CK_CF_Review CHECK (ReviewStatus IN ('suggested','confirmed','rejected','unknown')),
    CONSTRAINT CK_CF_Range  CHECK (EndPos IS NULL OR EndPos > StartPos),
    CONSTRAINT FK_CF_Book FOREIGN KEY (BookId) REFERENCES dbo.Books(BookId),
    CONSTRAINT FK_CF_Char FOREIGN KEY (CharacterId, BookId) REFERENCES dbo.Characters(CharacterId, BookId)
);
GO

------------------------------------------------------------------------------
-- 10. GlossaryTerms  (thuật ngữ + tiếng động 'sfx')
------------------------------------------------------------------------------
IF OBJECT_ID('dbo.GlossaryTerms','U') IS NULL
CREATE TABLE dbo.GlossaryTerms (
    TermId           INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_GlossaryTerms PRIMARY KEY,
    BookId           INT NOT NULL CONSTRAINT FK_Glossary_Books REFERENCES dbo.Books(BookId),
    SourceTerm       NVARCHAR(250) NOT NULL,
    TargetTerm       NVARCHAR(250) NOT NULL,
    TermType         VARCHAR(40)   NULL,                    -- place / organization / skill / item / honorific / sfx / term
    Notes            NVARCHAR(500) NULL,
    IsApproved       BIT NOT NULL CONSTRAINT DF_Glossary_Approved DEFAULT 0,
    IsActive         BIT NOT NULL CONSTRAINT DF_Glossary_Active DEFAULT 1,
    CreatedAt        DATETIME2(0) NOT NULL CONSTRAINT DF_Glossary_CreatedAt DEFAULT SYSUTCDATETIME(),
    Variants         NVARCHAR(500) NULL,                    -- các cách viết khác, ngăn bằng | hoặc ;
    DoNotTranslate   BIT NOT NULL CONSTRAINT DF_Glossary_DNT DEFAULT 0,
    FirstSeenChapter INT NULL,
    CONSTRAINT UQ_Glossary UNIQUE (BookId, SourceTerm)
);
GO

------------------------------------------------------------------------------
-- 11. ChapterScenes  (bối cảnh, thời gian, cảm xúc chủ đạo của từng cảnh)
------------------------------------------------------------------------------
IF OBJECT_ID('dbo.ChapterScenes','U') IS NULL
CREATE TABLE dbo.ChapterScenes (
    SceneId      INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_ChapterScenes PRIMARY KEY,
    BookId       INT NOT NULL,
    ChapterId    INT NOT NULL,
    SceneIndex   INT NOT NULL,
    StartPara    INT NOT NULL,                              -- bao gồm
    EndPara      INT NULL,                                  -- không bao gồm; NULL = hết chương
    Location     NVARCHAR(200)  NULL,
    TimeOfDay    NVARCHAR(100)  NULL,
    Mood         NVARCHAR(200)  NULL,
    SummaryVI    NVARCHAR(1000) NULL,
    ReviewStatus VARCHAR(20) NOT NULL CONSTRAINT DF_CS_Review DEFAULT 'suggested',
    CreatedAt    DATETIME2(0) NOT NULL CONSTRAINT DF_CS_CreatedAt DEFAULT SYSUTCDATETIME(),
    CONSTRAINT CK_CS_Review CHECK (ReviewStatus IN ('suggested','confirmed','rejected','unknown')),
    CONSTRAINT CK_CS_Range  CHECK (EndPara IS NULL OR EndPara > StartPara),
    CONSTRAINT FK_CS_Book    FOREIGN KEY (BookId) REFERENCES dbo.Books(BookId),
    CONSTRAINT FK_CS_Chapter FOREIGN KEY (ChapterId, BookId) REFERENCES dbo.Chapters(ChapterId, BookId),
    CONSTRAINT UQ_ChapterScenes UNIQUE (ChapterId, SceneIndex)
);
GO

------------------------------------------------------------------------------
-- 12. ChapterParagraphs  (KẾT QUẢ STAGE 1.5: nhãn từng đoạn + bản dịch; nguồn dựng chunk/context/train)
------------------------------------------------------------------------------
IF OBJECT_ID('dbo.ChapterParagraphs','U') IS NULL
CREATE TABLE dbo.ChapterParagraphs (
    ParagraphId   BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_ChapterParagraphs PRIMARY KEY,
    BookId        INT NOT NULL,
    ChapterId     INT NOT NULL,
    ChapterNumber INT NOT NULL,
    ParaIndex     INT NOT NULL,                             -- 1-based trong bản gốc đã làm sạch
    Pos AS (ChapterNumber * 100000 + ParaIndex) PERSISTED,
    SourceEN      NVARCHAR(MAX) NOT NULL,
    TargetVI      NVARCHAR(MAX) NULL,                       -- NULL với chương chưa dịch
    SourceHash    CHAR(64)      NOT NULL,
    Mode          VARCHAR(10)   NOT NULL,
    SpeakerId     INT NULL,
    ListenerId    INT NULL,
    SceneState    NVARCHAR(40)  NULL,
    SceneBreak    BIT NOT NULL CONSTRAINT DF_CP_SceneBreak DEFAULT 0,   -- đoạn này mở đầu một cảnh mới
    IsConfirmed   BIT NOT NULL CONSTRAINT DF_CP_Confirmed DEFAULT 0,
    AlignConf     VARCHAR(8)    NULL,
    Flags         NVARCHAR(400) NULL,
    Note          NVARCHAR(500) NULL,
    UpdatedAt     DATETIME2(0)  NOT NULL CONSTRAINT DF_CP_UpdatedAt DEFAULT SYSUTCDATETIME(),
    CONSTRAINT CK_CP_Mode  CHECK (Mode IN ('speech','thought','narration','system','sfx')),
    CONSTRAINT CK_CP_Index CHECK (ParaIndex > 0),
    CONSTRAINT FK_CP_Book     FOREIGN KEY (BookId) REFERENCES dbo.Books(BookId),
    CONSTRAINT FK_CP_Chapter  FOREIGN KEY (ChapterId, BookId)  REFERENCES dbo.Chapters(ChapterId, BookId),
    CONSTRAINT FK_CP_Speaker  FOREIGN KEY (SpeakerId, BookId)  REFERENCES dbo.Characters(CharacterId, BookId),
    CONSTRAINT FK_CP_Listener FOREIGN KEY (ListenerId, BookId) REFERENCES dbo.Characters(CharacterId, BookId),
    CONSTRAINT UQ_ChapterParagraphs UNIQUE (BookId, ChapterNumber, ParaIndex)
);
GO

------------------------------------------------------------------------------
-- 13. ModelVersions  (adapter LoRA trên Drive; phải khớp TemplateVersion với prompt_template.py)
------------------------------------------------------------------------------
IF OBJECT_ID('dbo.ModelVersions','U') IS NULL
CREATE TABLE dbo.ModelVersions (
    ModelVersionId  INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_ModelVersions PRIMARY KEY,
    BaseModel       NVARCHAR(100) NOT NULL,
    AdapterPath     NVARCHAR(400) NULL,
    TemplateVersion VARCHAR(20)   NOT NULL,
    TrainSetHash    CHAR(64)      NULL,
    TrainExamples   INT           NULL,
    Hyperparams     NVARCHAR(MAX) NULL,                     -- JSON: r, alpha, lr, epochs, max_seq_len...
    EvalResult      NVARCHAR(MAX) NULL,                     -- JSON: val_loss, pronoun_acc, term_acc...
    IsActive        BIT NOT NULL CONSTRAINT DF_MV_Active DEFAULT 0,
    CreatedAt       DATETIME2(0) NOT NULL CONSTRAINT DF_MV_CreatedAt DEFAULT SYSUTCDATETIME()
);
GO

------------------------------------------------------------------------------
-- 14. TranslationJobs  (mỗi lần export -> dịch -> import)
------------------------------------------------------------------------------
IF OBJECT_ID('dbo.TranslationJobs','U') IS NULL
CREATE TABLE dbo.TranslationJobs (
    JobId           INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_TranslationJobs PRIMARY KEY,
    BookId          INT NOT NULL,
    ChapterId       INT NOT NULL,
    ModelVersionId  INT NULL CONSTRAINT FK_TJ_Model REFERENCES dbo.ModelVersions(ModelVersionId),
    TemplateVersion VARCHAR(20) NOT NULL,
    JobStatus       VARCHAR(20) NOT NULL CONSTRAINT DF_TJ_Status DEFAULT 'exported',
    PendingFile     NVARCHAR(260) NULL,
    ResultFile      NVARCHAR(260) NULL,
    ChunkCount      INT NULL,
    FailedCount     INT NULL,
    Notes           NVARCHAR(500) NULL,
    ExportedAt      DATETIME2(0) NOT NULL CONSTRAINT DF_TJ_ExportedAt DEFAULT SYSUTCDATETIME(),
    ImportedAt      DATETIME2(0) NULL,
    CONSTRAINT CK_TJ_Status CHECK (JobStatus IN ('exported','running','imported','partial','failed')),
    CONSTRAINT FK_TJ_Book    FOREIGN KEY (BookId) REFERENCES dbo.Books(BookId),
    CONSTRAINT FK_TJ_Chapter FOREIGN KEY (ChapterId, BookId) REFERENCES dbo.Chapters(ChapterId, BookId)
);
GO

------------------------------------------------------------------------------
-- 15. TranslationContextSnapshots  (đúng JSON đã render thành prompt: truy vết + train = inference)
------------------------------------------------------------------------------
IF OBJECT_ID('dbo.TranslationContextSnapshots','U') IS NULL
CREATE TABLE dbo.TranslationContextSnapshots (
    SnapshotId      BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_TCS PRIMARY KEY,
    BookId          INT NOT NULL CONSTRAINT FK_TCS_Books REFERENCES dbo.Books(BookId),
    ChapterNumber   INT NOT NULL,
    ParaStart       INT NOT NULL,                           -- bao gồm
    ParaEnd         INT NOT NULL,                           -- không bao gồm
    TemplateVersion VARCHAR(20)   NOT NULL,
    ContextHash     CHAR(64)      NOT NULL,
    ContextJson     NVARCHAR(MAX) NOT NULL,
    CreatedAt       DATETIME2(0)  NOT NULL CONSTRAINT DF_TCS_CreatedAt DEFAULT SYSUTCDATETIME(),
    CONSTRAINT CK_TCS_Range CHECK (ParaEnd > ParaStart),
    CONSTRAINT UQ_Snapshot UNIQUE (BookId, ChapterNumber, ParaStart, ParaEnd, ContextHash)
);
GO

------------------------------------------------------------------------------
-- 16. TranslationChunks  (chỉ insert khi ĐÃ DỊCH XONG: TargetVI NOT NULL)
------------------------------------------------------------------------------
IF OBJECT_ID('dbo.TranslationChunks','U') IS NULL
CREATE TABLE dbo.TranslationChunks (
    ChunkId         INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_TranslationChunks PRIMARY KEY,
    ChapterId       INT NOT NULL CONSTRAINT FK_TC_Chapter REFERENCES dbo.Chapters(ChapterId),
    ChunkIndex      INT NOT NULL,                           -- 0-based
    SourceEN        NVARCHAR(MAX) NOT NULL,
    TargetVI        NVARCHAR(MAX) NOT NULL,
    SourceHash      CHAR(64) NOT NULL,
    ContextHash     CHAR(64) NOT NULL,
    ModelName       NVARCHAR(100) NULL,
    InputTokens     INT NULL,
    OutputTokens    INT NULL,
    UpdatedAt       DATETIME2(0) NOT NULL CONSTRAINT DF_TC_UpdatedAt DEFAULT SYSUTCDATETIME(),
    IsReviewed      BIT NOT NULL CONSTRAINT DF_TC_Reviewed DEFAULT 0,
    CreatedAt       DATETIME2(0) NOT NULL CONSTRAINT DF_TC_CreatedAt DEFAULT SYSUTCDATETIME(),
    LastJobId       INT NULL CONSTRAINT FK_TC_Job REFERENCES dbo.TranslationJobs(JobId),
    ParaStart       INT NULL,                               -- bao gồm
    ParaEnd         INT NULL,                               -- không bao gồm
    TemplateVersion VARCHAR(20) NULL,
    SnapshotId      BIGINT NULL CONSTRAINT FK_TC_Snapshot REFERENCES dbo.TranslationContextSnapshots(SnapshotId),
    ModelVersionId  INT NULL CONSTRAINT FK_TC_Model REFERENCES dbo.ModelVersions(ModelVersionId),
    QaFlags         VARCHAR(200) NULL,                      -- para_mismatch, think_tag, pronoun_violation...
    CONSTRAINT UQ_TranslationChunks UNIQUE (ChapterId, ChunkIndex)
);
GO

------------------------------------------------------------------------------
-- 17. TranslationCorrections  (lịch sử sửa; sửa được ở mức CHUNK hoặc mức ĐOẠN)
------------------------------------------------------------------------------
IF OBJECT_ID('dbo.TranslationCorrections','U') IS NULL
CREATE TABLE dbo.TranslationCorrections (
    CorrectionId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_TranslationCorrections PRIMARY KEY,
    ChunkId      INT    NULL CONSTRAINT FK_Corr_Chunk REFERENCES dbo.TranslationChunks(ChunkId),
    ParagraphId  BIGINT NULL CONSTRAINT FK_Corr_Para  REFERENCES dbo.ChapterParagraphs(ParagraphId),
    DraftVI      NVARCHAR(MAX) NOT NULL,
    CorrectedVI  NVARCHAR(MAX) NOT NULL,
    ErrorType    VARCHAR(30)   NULL,
    CommentVI    NVARCHAR(1000) NULL,
    IsApproved   BIT NOT NULL CONSTRAINT DF_Corr_Approved DEFAULT 0,
    CreatedAt    DATETIME2(0) NOT NULL CONSTRAINT DF_Corr_CreatedAt DEFAULT SYSUTCDATETIME(),
    CONSTRAINT CK_Corr_Target CHECK (ChunkId IS NOT NULL OR ParagraphId IS NOT NULL),
    CONSTRAINT CK_Corr_Type CHECK (ErrorType IS NULL OR ErrorType IN
        ('pronoun','emotion','terminology','meaning','style','missing','other'))
);
GO

------------------------------------------------------------------------------
-- 18. TranslationExamples  (few-shot / train đã duyệt)
------------------------------------------------------------------------------
IF OBJECT_ID('dbo.TranslationExamples','U') IS NULL
CREATE TABLE dbo.TranslationExamples (
    ExampleId       INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_TranslationExamples PRIMARY KEY,
    BookId          INT NOT NULL,
    ExampleKey      CHAR(64) NOT NULL,                      -- SHA-256 chống nhập trùng
    SpeakerId       INT NULL,
    ListenerId      INT NULL,
    SceneState      NVARCHAR(40) NULL,
    SourceEN        NVARCHAR(MAX) NOT NULL,
    TargetVI        NVARCHAR(MAX) NOT NULL,
    IsApproved      BIT NOT NULL CONSTRAINT DF_TE_Approved DEFAULT 0,
    CreatedAt       DATETIME2(0) NOT NULL CONSTRAINT DF_TE_CreatedAt DEFAULT SYSUTCDATETIME(),
    SourceChunkId   INT NULL CONSTRAINT FK_TE_Chunk REFERENCES dbo.TranslationChunks(ChunkId),
    ApprovedAt      DATETIME2(0) NULL,
    StyleTags       NVARCHAR(250) NULL,
    Granularity     VARCHAR(10) NOT NULL CONSTRAINT DF_TE_Gran DEFAULT 'line',
    ChapterId       INT NULL CONSTRAINT FK_TE_Chapter REFERENCES dbo.Chapters(ChapterId),
    ChunkIndex      INT NULL,
    SnapshotId      BIGINT NULL CONSTRAINT FK_TE_Snapshot REFERENCES dbo.TranslationContextSnapshots(SnapshotId),
    Split           VARCHAR(5) NOT NULL CONSTRAINT DF_TE_Split DEFAULT 'train',
    TemplateVersion VARCHAR(20) NULL,
    CONSTRAINT CK_TE_Gran  CHECK (Granularity IN ('line','mid','chunk')),
    CONSTRAINT CK_TE_Split CHECK (Split IN ('train','val','test')),
    CONSTRAINT FK_TE_Book     FOREIGN KEY (BookId) REFERENCES dbo.Books(BookId),
    CONSTRAINT FK_TE_Speaker  FOREIGN KEY (SpeakerId, BookId)  REFERENCES dbo.Characters(CharacterId, BookId),
    CONSTRAINT FK_TE_Listener FOREIGN KEY (ListenerId, BookId) REFERENCES dbo.Characters(CharacterId, BookId),
    CONSTRAINT UQ_TE_Key UNIQUE (BookId, ExampleKey)
);
GO

------------------------------------------------------------------------------
-- 19. View tiện kiểm tra
------------------------------------------------------------------------------
CREATE OR ALTER VIEW dbo.vw_ChapterParagraphs AS
SELECT p.BookId, p.ChapterNumber, p.ParaIndex, p.Mode,
       s.Name AS Speaker, l.Name AS Listener, p.SceneState, p.SceneBreak, p.IsConfirmed,
       p.SourceEN, p.TargetVI
FROM dbo.ChapterParagraphs p
LEFT JOIN dbo.Characters s ON s.CharacterId = p.SpeakerId
LEFT JOIN dbo.Characters l ON l.CharacterId = p.ListenerId;
GO
CREATE OR ALTER VIEW dbo.vw_PronounRulesNamed AS
SELECT r.RuleId, r.BookId, s.Name AS Speaker, l.Name AS Listener, r.SpeechMode, r.SceneState,
       r.SelfPronoun, r.AddressPronoun, r.ReferPronoun, r.StartPos, r.EndPos, r.IsConfirmed, r.Notes
FROM dbo.PronounRules r
JOIN dbo.Characters s ON s.CharacterId = r.SpeakerId
LEFT JOIN dbo.Characters l ON l.CharacterId = r.ListenerId;
GO
-- Mỗi dòng là một vấn đề cần xử lý TRƯỚC khi export-train (rỗng = sạch)
CREATE OR ALTER VIEW dbo.vw_ParagraphIssues AS
SELECT p.BookId, p.ChapterNumber, p.ParaIndex, CAST('speech_or_thought_without_speaker' AS VARCHAR(40)) AS Issue
FROM dbo.ChapterParagraphs p
WHERE p.Mode IN ('speech','thought') AND p.SpeakerId IS NULL
UNION ALL
SELECT p.BookId, p.ChapterNumber, p.ParaIndex, 'chapter_number_mismatch'
FROM dbo.ChapterParagraphs p
JOIN dbo.Chapters c ON c.ChapterId = p.ChapterId
WHERE c.ChapterNumber <> p.ChapterNumber
UNION ALL
SELECT p.BookId, p.ChapterNumber, p.ParaIndex, 'confirmed_without_target'
FROM dbo.ChapterParagraphs p
WHERE p.IsConfirmed = 1 AND (p.TargetVI IS NULL OR LTRIM(RTRIM(p.TargetVI)) = N'')
UNION ALL
SELECT p.BookId, p.ChapterNumber, p.ParaIndex, 'merged_target_placeholder'
FROM dbo.ChapterParagraphs p
WHERE p.TargetVI LIKE N'(gộp%'
UNION ALL
SELECT p.BookId, p.ChapterNumber, NULL, 'para_index_gap'
FROM dbo.ChapterParagraphs p
GROUP BY p.BookId, p.ChapterNumber
HAVING MAX(p.ParaIndex) <> COUNT(*);
GO

------------------------------------------------------------------------------
-- 20. Dữ liệu khởi tạo
------------------------------------------------------------------------------
IF NOT EXISTS (SELECT 1 FROM dbo.Books WHERE BookKey = N'blue-archive')
    INSERT INTO dbo.Books (BookKey, Title, StyleGuide, UpdatedAt)
    VALUES (N'blue-archive', N'Blue Archive: Nơi Mọi Thù Hận Bắt Đầu', N'', SYSUTCDATETIME());
GO
IF NOT EXISTS (SELECT 1 FROM dbo.SchemaInfo WHERE SchemaVersion = 'v3-full')
    INSERT INTO dbo.SchemaInfo (SchemaVersion, Notes) VALUES ('v3-full', N'18 bảng, tạo từ đầu');
GO

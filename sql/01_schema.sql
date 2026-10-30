-- ContextTranslate - chạy toàn bộ trong SSMS (New Query -> Execute)
-- Yêu cầu: tài khoản có quyền tạo database và table.

"""Books: Lưu thông tin truyện (tiêu đề, thể loại, hướng dẫn văn phong chung StyleGuide).
Characters: Danh sách các nhân vật trong truyện.
PronounRules: Bảng quy tắc xưng hô giữa 2 nhân vật theo từng ngữ cảnh (normal, hostile, reconciliation,...).
TranslationExamples: Các cặp câu dịch mẫu Anh - Việt, có cờ IsApproved (chỉ những câu đã duyệt mới được đưa vào Prompt).
Chapters: Quản lý các chương và phần tóm tắt nội dung (SummaryVI). 
TranslationChunks: Lưu từng đoạn dịch, mã băm nguồn/ngữ cảnh, model AI và số token tiêu thụ.
"""

IF DB_ID(N'ContextTranslateDB') IS NULL
BEGIN
    CREATE DATABASE ContextTranslateDB;
END;
GO
USE ContextTranslateDB;
GO

IF OBJECT_ID(N'dbo.Books', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.Books (
        BookId INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        BookKey NVARCHAR(120) NOT NULL UNIQUE,
        Title NVARCHAR(250) NOT NULL,
        Genre NVARCHAR(120) NULL,
        StyleGuide NVARCHAR(MAX) NULL,
        CreatedAt DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
    );
END;
GO

IF OBJECT_ID(N'dbo.Characters', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.Characters (
        CharacterId INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        BookId INT NOT NULL,
        Name NVARCHAR(120) NOT NULL,
        Notes NVARCHAR(MAX) NULL,
        CONSTRAINT FK_Characters_Books FOREIGN KEY (BookId) REFERENCES dbo.Books(BookId),
        CONSTRAINT UQ_Characters_BookName UNIQUE (BookId, Name),
        CONSTRAINT UQ_Characters_BookId_CharacterId UNIQUE (BookId, CharacterId)
    );
END;
GO

IF OBJECT_ID(N'dbo.PronounRules', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.PronounRules (
        RuleId INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        BookId INT NOT NULL,
        SpeakerId INT NOT NULL,
        ListenerId INT NOT NULL,
        SceneState NVARCHAR(40) NOT NULL,
        SelfPronoun NVARCHAR(60) NOT NULL,
        AddressPronoun NVARCHAR(60) NOT NULL,
        Notes NVARCHAR(500) NULL,
        CONSTRAINT FK_Rules_Books FOREIGN KEY (BookId) REFERENCES dbo.Books(BookId),
        CONSTRAINT FK_Rules_Speaker FOREIGN KEY (BookId, SpeakerId)
            REFERENCES dbo.Characters(BookId, CharacterId),
        CONSTRAINT FK_Rules_Listener FOREIGN KEY (BookId, ListenerId)
            REFERENCES dbo.Characters(BookId, CharacterId),
        CONSTRAINT UQ_Rules UNIQUE (BookId, SpeakerId, ListenerId, SceneState)
    );
END;
GO

IF OBJECT_ID(N'dbo.TranslationExamples', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.TranslationExamples (
        ExampleId INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        BookId INT NOT NULL,
        ExampleKey CHAR(64) NOT NULL,
        SpeakerId INT NULL,
        ListenerId INT NULL,
        SceneState NVARCHAR(40) NOT NULL DEFAULT N'general',
        SourceEN NVARCHAR(MAX) NOT NULL,
        TargetVI NVARCHAR(MAX) NOT NULL,
        IsApproved BIT NOT NULL DEFAULT 0,
        CreatedAt DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT FK_Examples_Books FOREIGN KEY (BookId) REFERENCES dbo.Books(BookId),
        CONSTRAINT FK_Examples_Speaker FOREIGN KEY (BookId, SpeakerId)
            REFERENCES dbo.Characters(BookId, CharacterId),
        CONSTRAINT FK_Examples_Listener FOREIGN KEY (BookId, ListenerId)
            REFERENCES dbo.Characters(BookId, CharacterId),
        CONSTRAINT UQ_Examples_Key UNIQUE (BookId, ExampleKey)
    );
    CREATE INDEX IX_Examples_Filter ON dbo.TranslationExamples (BookId, IsApproved, SceneState);
END;
GO

IF OBJECT_ID(N'dbo.Chapters', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.Chapters (
        ChapterId INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        BookId INT NOT NULL,
        ChapterNumber INT NOT NULL,
        Title NVARCHAR(250) NULL,
        SummaryVI NVARCHAR(MAX) NULL,
        CreatedAt DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT FK_Chapters_Books FOREIGN KEY (BookId) REFERENCES dbo.Books(BookId),
        CONSTRAINT UQ_Chapters_BookNumber UNIQUE (BookId, ChapterNumber)
    );
END;
GO

IF OBJECT_ID(N'dbo.TranslationChunks', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.TranslationChunks (
        ChunkId INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        ChapterId INT NOT NULL,
        ChunkIndex INT NOT NULL,
        SourceEN NVARCHAR(MAX) NOT NULL,
        TargetVI NVARCHAR(MAX) NOT NULL,
        SourceHash CHAR(64) NOT NULL,
        ContextHash CHAR(64) NOT NULL,
        ModelName NVARCHAR(100) NOT NULL,
        InputTokens INT NULL,
        OutputTokens INT NULL,
        UpdatedAt DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT FK_Chunks_Chapters FOREIGN KEY (ChapterId) REFERENCES dbo.Chapters(ChapterId),
        CONSTRAINT UQ_Chunks_ChapterIndex UNIQUE (ChapterId, ChunkIndex)
    );
END;
GO

PRINT N'Đã tạo/kiểm tra 6 bảng của ContextTranslateDB.';
GO

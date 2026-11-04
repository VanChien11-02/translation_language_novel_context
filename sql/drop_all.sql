-- ============================================================================
-- !!! CHỈ DÙNG KHI PHÁT TRIỂN: XÓA TOÀN BỘ bảng/view/trigger của schema v3 (MẤT HẾT DỮ LIỆU) !!!
-- Chạy trong DB ContextTranslate rồi chạy lại 020_schema_full_v3.sql để làm lại từ đầu.
-- ============================================================================
DROP VIEW IF EXISTS dbo.vw_ParagraphIssues;
DROP VIEW IF EXISTS dbo.vw_PronounRulesNamed;
DROP VIEW IF EXISTS dbo.vw_ChapterParagraphs;
GO
DROP TABLE IF EXISTS dbo.TranslationExamples;
DROP TABLE IF EXISTS dbo.TranslationCorrections;
DROP TABLE IF EXISTS dbo.TranslationChunks;
DROP TABLE IF EXISTS dbo.TranslationContextSnapshots;
DROP TABLE IF EXISTS dbo.TranslationJobs;
DROP TABLE IF EXISTS dbo.ModelVersions;
DROP TABLE IF EXISTS dbo.ChapterParagraphs;
DROP TABLE IF EXISTS dbo.ChapterScenes;
DROP TABLE IF EXISTS dbo.GlossaryTerms;
DROP TABLE IF EXISTS dbo.ContextFacts;
DROP TABLE IF EXISTS dbo.PronounRules;          -- trigger đi theo bảng
DROP TABLE IF EXISTS dbo.StoryEventCharacters;
DROP TABLE IF EXISTS dbo.StoryEvents;
DROP TABLE IF EXISTS dbo.CharacterRelationships;
DROP TABLE IF EXISTS dbo.CharacterAliases;
DROP TABLE IF EXISTS dbo.Characters;
DROP TABLE IF EXISTS dbo.Chapters;
DROP TABLE IF EXISTS dbo.Books;
DROP TABLE IF EXISTS dbo.SchemaInfo;
GO

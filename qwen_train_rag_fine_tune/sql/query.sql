USE ContextTranslateDB;

SELECT * FROM dbo.Books;
SELECT * FROM dbo.Characters;
SELECT * FROM dbo.PronounRules;
SELECT * FROM dbo.TranslationExamples;

-- Xem cách xưng hô theo trạng thái:
SELECT s.Name AS Speaker, l.Name AS Listener, r.SceneState,
       r.SelfPronoun, r.AddressPronoun
FROM dbo.PronounRules r
JOIN dbo.Characters s ON s.CharacterId = r.SpeakerId
JOIN dbo.Characters l ON l.CharacterId = r.ListenerId
WHERE r.BookId = 1;

-- Kiểm tra bản dịch đã được lưu, theo chương:
SELECT c.ChapterNumber, t.ChunkIndex, t.SourceEN, t.TargetVI,
       t.ModelName, t.InputTokens, t.OutputTokens
FROM dbo.TranslationChunks t
JOIN dbo.Chapters c ON c.ChapterId = t.ChapterId
ORDER BY c.ChapterNumber, t.ChunkIndex;
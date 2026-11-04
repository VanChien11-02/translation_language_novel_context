-- ============================================================================
-- Tạo DATABASE (chạy MỘT lần, trong SSMS / sqlcmd, kết nối vào master).
-- Collation Vietnamese_CI_AS: không phân biệt hoa/thường nhưng PHÂN BIỆT dấu (em ≠ êm), sắp xếp theo tiếng Việt.
-- Nếu đã có DB: bỏ qua file này và chạy thẳng 020_schema_full_v3.sql trong DB đó.
-- ============================================================================
IF DB_ID(N'ContextTranslate') IS NULL
    CREATE DATABASE ContextTranslate COLLATE Vietnamese_CI_AS;
GO

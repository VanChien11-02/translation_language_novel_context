"""Cấu hình dùng chung. Chỉnh file này (hoặc đặt biến môi trường CTX_CONN)."""
import os

BOOK_KEY = "blue-archive"
BOOK_TITLE = "Blue Archive: Nơi Mọi Thù Hận Bắt Đầu"

# Chuỗi kết nối SQL Server (cần: pip install pyodbc + ODBC Driver 18 for SQL Server).
# Ví dụ Windows Authentication:
SQLSERVER_CONN = os.environ.get(
    "CTX_CONN",
    "DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost;DATABASE=ContextTranslate;"
    "Trusted_Connection=yes;TrustServerCertificate=yes",
)

SEED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed")

# Từ vựng nhãn (khớp dropdown trong annotation_sheet.xlsx)
MODES = ["speech", "thought", "narration", "system", "sfx"]
STATES = ["normal", "worried", "hostile", "sarcastic", "panic", "regret", "pleading", "joking",
          "serious", "sad", "tired", "happy", "suffer", "chill"]
GROUP_NAMES = {"Group", "Crowd"}          # nhãn nhóm chung chung (không phải một nhân vật)
NARRATOR = "Narrator"

# Quy cách chunk (xem spec mục 4.5)
CHUNK_MAX_PARAS = 14
CHUNK_MAX_CHARS = 1800
MID_MAX_PARAS = 5
MID_MAX_CHARS = 700
SLIDING_OFFSETS = (0, 2, 4)               # tăng dữ liệu hợp lệ bằng cách lệch biên chunk
PREV_PROB = 0.7                           # tỷ lệ mẫu train có khối <prev>
EXAMPLES_PROB = 0.5                       # tỷ lệ mẫu train có khối <examples>
RNG_SEED = 13

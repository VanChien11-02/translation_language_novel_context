"""Xuất các ví dụ đã được bạn duyệt từ SQL Server thành CSV cho notebook.
Lấy cấu hình từ .env của project SQL Server trước đó. Chạy trong thư mục đó
hoặc đặt .env tương ứng ở thư mục script.
"""
import os, csv
from pathlib import Path
from dotenv import load_dotenv
import pyodbc

load_dotenv()
server=os.getenv('SQL_SERVER',r'.\SQLEXPRESS')
database=os.getenv('SQL_DATABASE','ContextTranslateDB')
driver=os.getenv('SQL_DRIVER','ODBC Driver 18 for SQL Server')
trust=os.getenv('SQL_TRUST_SERVER_CERTIFICATE','yes')
parts=[f'DRIVER={{{driver}}}',f'SERVER={server}',f'DATABASE={database}',
       'Encrypt=yes',f'TrustServerCertificate={trust}']
if os.getenv('SQL_USER'):
    parts.extend([f'UID={os.getenv("SQL_USER")}',f'PWD={os.getenv("SQL_PASSWORD", "")}'])
else:
    parts.append('Trusted_Connection=yes')

with pyodbc.connect(';'.join(parts)) as conn:
    cur=conn.cursor()
    # Lấy các cặp đã được con người duyệt, không dùng raw AI chưa kiểm chứng.
    cur.execute("""SELECT e.SourceEN,e.TargetVI, c1.Name,c2.Name,e.SceneState
                   FROM dbo.TranslationExamples e
                   LEFT JOIN dbo.Characters c1 ON c1.CharacterId=e.SpeakerId
                   LEFT JOIN dbo.Characters c2 ON c2.CharacterId=e.ListenerId
                   WHERE e.IsApproved=1 ORDER BY e.ExampleId""")
    data=cur.fetchall()

out=Path('novel_pairs_approved.csv')
with out.open('w',newline='',encoding='utf-8-sig') as f:
    w=csv.writer(f)
    w.writerow(['source_en','target_vi','speaker','listener','scene','human_reviewed'])
    for r in data:
        w.writerow([r[0],r[1],r[2] or '',r[3] or '',r[4] or 'general',1])
print(f'Đã xuất {len(data)} ví dụ được duyệt ra {out.resolve()}')

from dao import Store

with Store() as store:
    row = store.stats()
    print('Kết nối SQL Server thành công!')
    print(f'Books: {row[0]}, Characters: {row[1]}, Examples: {row[2]}, Chunks: {row[3]}')

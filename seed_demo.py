"""Thêm dữ liệu mẫu Blue Archive; chạy lại không tạo bản ghi trùng."""
from dao import Store

STYLE = (
    'Dịch Anh-Việt theo phong cách light novel tự nhiên; giữ nguyên tên riêng '
    'Sensei, Yuuka, Arona, Plana, Saori và Schale. '
    'Giữ sắc thái cảm xúc, không tự thêm tình tiết. '
    'Khi chưa rõ ai nói với ai, không áp một quy tắc xưng hô tuỳ tiện. '
    'Lời dẫn có thể dùng anh/cô ấy tùy nhân vật, độc thoại nội tâm thường là mình.'
)

with Store() as store:
    book_id = store.ensure_book('blue-archive',
                               'Blue Archive: Nơi Mọi Thù Hận Bắt Đầu',
                               'Drama, Action, Fanfiction', STYLE)
    for name, note in [
        ('Sensei', 'Giáo viên, được học sinh gọi là thầy.'),
        ('Yuuka', 'Học sinh; đôi khi thay đổi cách xưng hô khi bị kích động.'),
        ('Arona', 'Gọi Sensei là thầy, tự xưng em.'),
        ('Plana', 'Gọi Sensei là thầy, tự xưng em.'),
        ('Saori', 'Quan hệ với Sensei thay đổi theo diễn biến.'),
        ('Black Suit', 'Nói với Sensei theo lối tôi/anh.'),
    ]:
        store.ensure_character(book_id, name, note)
    for speaker, listener, scene, me, you, notes in [
        ('Sensei', 'Yuuka', 'normal', 'thầy', 'em', 'Giọng thân thiết, lo lắng.'),
        ('Yuuka', 'Sensei', 'normal', 'em', 'thầy', 'Xưng hô bình thường.'),
        ('Yuuka', 'Sensei', 'hostile', 'ta', 'ngươi', 'Chỉ khi Yuuka đang thù địch.'),
        ('Arona', 'Sensei', 'normal', 'em', 'thầy', ''),
        ('Plana', 'Sensei', 'normal', 'em', 'thầy', ''),
        ('Sensei', 'Arona', 'normal', 'thầy', 'em', ''),
        ('Sensei', 'Plana', 'normal', 'thầy', 'em', ''),
        ('Black Suit', 'Sensei', 'normal', 'tôi', 'anh', ''),
        ('Saori', 'Sensei', 'hostile', 'ta', 'ngươi', 'Ví dụ minh họa: phải xét cảnh.'),
        ('Saori', 'Sensei', 'reconciliation', 'em', 'thầy', 'Hối hận và hòa giải.'),
    ]:
        store.ensure_rule(book_id, speaker, listener, scene, me, you, notes)

    # Các cặp minh họa được đối chiếu từ hai file Word người dùng cung cấp.
    # Đã biên tập dấu câu/chính tả tối thiểu cho demo. Nên tự duyệt lại trước khi dùng lâu dài.
    examples = [
        ('Hello, Yuuka. Where are you! Are you okay?',
         'Alo, Yuuka. Em đang ở đâu! Em ổn chứ?', 'Sensei', 'Yuuka', 'normal'),
        ('Why are you alive? Could it be, you weren\'t there?',
         'Tại sao ngươi còn sống? Chẳng lẽ ngươi không hề ở đó sao?',
         'Yuuka', 'Sensei', 'hostile'),
        ('Sensei was stunned by the sudden turn of events, but at this moment, one person came to mind.',
         'Sensei sửng sốt trước diễn biến đột ngột của sự việc, nhưng lúc này, có một người hiện lên trong tâm trí.',
         None, None, 'general'),
    ]
    for en, vi, sp, li, scene in examples:
        store.ensure_example(book_id, en, vi, sp, li, scene, approved=True)

print('Đã seed truyện, 6 nhân vật, quy tắc xưng hô và 3 cặp dịch mẫu.')

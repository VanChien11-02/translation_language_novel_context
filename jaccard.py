""" Jaccard dùng để tính độ tương đồng giữa hai tập hợp. 
Nó được định nghĩa là tỷ lệ giữa số lượng phần tử chung 
(giao nhau) và số lượng phần tử trong hợp (hợp nhất) của hai tập hợp. """

"""trong project này, jaccard được dùng để tính độ tương đồng giữa 
các câu tiếng Anh trong cơ sở dữ liệu với câu tiếng Anh được nhập vào."""

def jaccard(a, b):
    intersection = len(set(a) & set(b)) # 2
    union = len(set(a) | set(b)) # 5
    return intersection / union if union != 0 else 0

a = {"apple", "banana", "cherry"}
b = {"banana", "cherry", "date", "fig"}
similarity = jaccard(a, b)
print(similarity)  # Output: 0.4
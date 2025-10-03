import ast
import os
from collections import defaultdict
import hashlib

def get_python_files(directory: str) -> list[str]:
    """
    Lấy danh sách tất cả các file Python trong thư mục và các thư mục con.
    """
    python_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".py"):
                python_files.append(os.path.join(root, file))
    return python_files

class FunctionAnalyzer(ast.NodeVisitor):
    """
    Phân tích các định nghĩa hàm và lời gọi hàm trong một file.
    """
    def __init__(self):
        self.defined_functions = defaultdict(list) # {function_name: [(filepath, lineno, col_offset)]}
        self.called_functions = defaultdict(list)  # {function_name: [(filepath, lineno, col_offset)]}
        self.placeholders = defaultdict(list)      # {function_name: [(filepath, lineno, col_offset)]}

    def visit_FunctionDef(self, node):
        self.defined_functions[node.name].append((self.current_filepath, node.lineno, node.col_offset))
        # Kiểm tra hàm giữ chỗ
        if (len(node.body) == 1 and isinstance(node.body[0], (ast.Pass, ast.Ellipsis))) or \
           (len(node.body) > 0 and isinstance(node.body[0], ast.Expr) and
            isinstance(node.body[0].value, ast.Constant) and
            isinstance(node.body[0].value.value, str) and
            ("TODO" in node.body[0].value.value or "chưa triển khai" in node.body[0].value.value)):
            self.placeholders[node.name].append((self.current_filepath, node.lineno, node.col_offset))
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name):
            self.called_functions[node.func.id].append((self.current_filepath, node.lineno, node.col_offset))
        elif isinstance(node.func, ast.Attribute):
            self.called_functions[node.func.attr].append((self.current_filepath, node.lineno, node.col_offset))
        self.generic_visit(node)

def analyze_project(project_directory: str):
    """
    Phân tích toàn bộ dự án Python để tìm hàm không sử dụng, trùng lặp và giữ chỗ.
    """
    python_files = get_python_files(project_directory)
    all_defined_functions = defaultdict(list)
    all_called_functions = defaultdict(list)
    all_placeholders = defaultdict(list)
    function_contents = defaultdict(list) # {content_hash: [(function_name, filepath, lineno)]}

    print("Đang phân tích các file Python...")
    for filepath in python_files:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            tree = ast.parse(content, filename=filepath)
            analyzer = FunctionAnalyzer()
            analyzer.current_filepath = filepath # Gán filepath cho analyzer
            analyzer.visit(tree)

            for func_name, locations in analyzer.defined_functions.items():
                all_defined_functions[func_name].extend(locations)
                # Lấy nội dung hàm để kiểm tra trùng lặp
                for loc in locations:
                    start_line = loc[1] - 1
                    end_line = start_line
                    lines = content.splitlines()
                    # Tìm dòng kết thúc của hàm (đơn giản hóa, có thể cần cải tiến)
                    indentation = len(lines[start_line]) - len(lines[start_line].lstrip())
                    for i in range(start_line + 1, len(lines)):
                        if not lines[i].strip(): # Bỏ qua dòng trống
                            continue
                        current_indentation = len(lines[i]) - len(lines[i].lstrip())
                        if current_indentation <= indentation and lines[i].strip():
                            break
                        end_line = i
                    func_content = "\n".join(lines[start_line : end_line + 1])
                    content_hash = hashlib.md5(func_content.encode('utf-8')).hexdigest()
                    function_contents[content_hash].append((func_name, filepath, loc[1]))

            all_called_functions.update(analyzer.called_functions)
            for func_name, locations in analyzer.placeholders.items():
                all_placeholders[func_name].extend(locations)

        except Exception as e:
            print(f"Lỗi khi phân tích file {filepath}: {e}")

    # 1. Hàm không sử dụng
    unused_functions = {}
    for func_name, locations in all_defined_functions.items():
        if func_name not in all_called_functions:
            unused_functions[func_name] = locations

    # 2. Hàm trùng lặp
    duplicate_functions = defaultdict(list)
    for content_hash, funcs in function_contents.items():
        if len(funcs) > 1:
            # Lọc bỏ các hàm có cùng tên và cùng file (có thể là overload hoặc method khác nhau)
            unique_funcs = []
            seen = set()
            for func_name, filepath, lineno in funcs:
                if (func_name, filepath) not in seen:
                    unique_funcs.append((func_name, filepath, lineno))
                    seen.add((func_name, filepath))
            if len(unique_funcs) > 1:
                duplicate_functions[content_hash].extend(unique_funcs)

    print("\n--- BÁO CÁO PHÂN TÍCH CODE ---")

    if unused_functions:
        print("\n### 1. Các hàm không được sử dụng:")
        for func_name, locations in unused_functions.items():
            print(f"- `{func_name}`:")
            for filepath, lineno, _ in locations:
                print(f"  - Định nghĩa tại: {os.path.relpath(filepath, project_directory)} (dòng {lineno})")
    else:
        print("\n### 1. Không tìm thấy hàm không được sử dụng.")

    if duplicate_functions:
        print("\n### 2. Các hàm có logic trùng lặp:")
        for content_hash, funcs in duplicate_functions.items():
            print(f"- Các hàm trùng lặp (hash: {content_hash[:8]}):")
            for func_name, filepath, lineno in funcs:
                print(f"  - `{func_name}` tại: {os.path.relpath(filepath, project_directory)} (dòng {lineno})")
            print("  -> Cần xem xét hợp nhất hoặc loại bỏ các hàm này, ưu tiên hàm chi tiết hơn.")
    else:
        print("\n### 2. Không tìm thấy hàm trùng lặp.")

    if all_placeholders:
        print("\n### 3. Các hàm giữ chỗ (chưa có logic chi tiết thực tế):")
        for func_name, locations in all_placeholders.items():
            print(f"- `{func_name}`:")
            for filepath, lineno, _ in locations:
                print(f"  - Tại: {os.path.relpath(filepath, project_directory)} (dòng {lineno})")
    else:
        print("\n### 3. Không tìm thấy hàm giữ chỗ.")

if __name__ == "__main__":
    project_root = "src" # Thư mục gốc của dự án Python
    analyze_project(project_root)

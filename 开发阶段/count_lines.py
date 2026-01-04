"""统计开发阶段文档的总行数"""
import os

folder = r"E:\Individual Project\开发阶段"
total = 0

for f in os.listdir(folder):
    if f.endswith(".md"):
        path = os.path.join(folder, f)
        with open(path, "r", encoding="utf-8") as file:
            lines = len(file.readlines())
            print(f"{f}: {lines} 行")
            total += lines

print(f"\n总计: {total} 行")

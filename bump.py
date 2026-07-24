import sys
files = [
    "python/zedda/__init__.py",
    "python/zedda/cli.py",
    "CMakeLists.txt",
    "tests/python/test_fasteda.py",
    "tests/python/test_extracted_modules.py"
]

for f in files:
    with open(f, 'r', encoding='utf-8') as file:
        content = file.read()
    
    content = content.replace("0.4.7", "0.4.8")
    
    with open(f, 'w', encoding='utf-8') as file:
        file.write(content)
    print(f"Updated {f}")

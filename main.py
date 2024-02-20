import ast
import collections
import os
import sys

if sys.version_info < (3, 11):
    import toml
else:
    import tomllib as toml

class CallInfo:
    def __init__(self):
        # caller -> [(callee, count)]
        self.call_relations = collections.defaultdict(lambda: collections.defaultdict(int))

    def add_call(self, caller, callee):
        self.call_relations[caller][callee] += 1

    def display(self):
        for caller, callees in self.call_relations.items():
            print(f"{caller}:")
            for callee, count in callees.items():
                print(f"  -> {callee} (called {count} times)")

class EventAnalysisVisitor(ast.NodeVisitor):
    def __init__(self, call_info, current_file):
        self.call_info = call_info
        self.current_class = None
        self.current_file = current_file

    def visit_ClassDef(self, node):
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = None

    def visit_Call(self, node):
        callee = self.get_callee(node)
        if callee:
            caller = self.current_class or "Global Scope"
            self.call_info.add_call(f"{caller} in {self.current_file}", callee)
        self.generic_visit(node)

    def get_callee(self, node):
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            return f"{node.func.value.id}.{node.func.attr}"
        elif isinstance(node.func, ast.Name):
            return node.func.id
        return None

def load_config():
    try:
        with open("pyproject.toml", "r", encoding="utf-8") as toml_file:
            if sys.version_info < (3, 11):
                config = toml.load(toml_file)
            else:
                config = toml.load(toml_file)
        return config.get("tool", {}).get("py-flow-trace", {}).get("ignore", [])
    except FileNotFoundError:
        return []

def analyze_file(file_path, call_info):
    with open(file_path, "r", encoding="utf-8") as file:
        source_code = file.read()
    tree = ast.parse(source_code, filename=file_path)
    visitor = EventAnalysisVisitor(call_info, file_path)
    visitor.visit(tree)

def walk_and_analyze(directory, ignore_list):
    call_info = CallInfo()
    for root, dirs, files in os.walk(directory, topdown=True):
        dirs[:] = [d for d in dirs if not any(ig in os.path.join(root, d) for ig in ignore_list)]
        for file in files:
            if file.endswith(".py") and not any(ig in os.path.join(root, file) for ig in ignore_list):
                analyze_file(os.path.join(root, file), call_info)
    call_info.display()

ignore_list = load_config()
ignore_list += ["__pycache__", ".git", ".venv", "venv", "env"]
project_directory = "."  # 혹은 분석하고 싶은 프로젝트의 루트 디렉토리 경로
walk_and_analyze(project_directory, ignore_list)

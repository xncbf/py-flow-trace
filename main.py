import ast
import builtins
import collections
import json
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


def get_module_path(file_path):
    # 파일 경로를 Python 모듈 경로로 변환
    module_path, _ = os.path.splitext(file_path)  # 확장자 제거
    # 설정의 path 기준으로 상대 경로로 변환
    module_path = os.path.relpath(module_path, settings["path"])
    return module_path.replace(os.path.sep, ".")  # 경로 구분자를 '.'으로 변경


class EventAnalysisVisitor(ast.NodeVisitor):
    def __init__(self, call_info, current_file):
        self.call_info = call_info
        self.current_class = None
        self.current_file = current_file
        self.current_method = None  # 현재 방문 중인 메서드를 추적하기 위한 변수 추가
        self.imports = {}  # import 이름과 실제 모듈/클래스의 매핑을 저장
        self.builtin_modules = dir(builtins)
        self.third_party_modules = set()

    def visit_Import(self, node):
        for alias in node.names:
            self.imports[alias.name] = alias.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        module = node.module
        for alias in node.names:
            full_name = f"{module}.{alias.name}"
            self.imports[alias.name] = full_name
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = None
        self.current_method = None  # 클래스를 벗어날 때 컨텍스트 리셋

    def visit_FunctionDef(self, node):
        if self.current_class:  # 클래스 내부의 메서드인 경우
            self.current_method = node.name
        self.generic_visit(node)
        self.current_method = None  # 메서드 방문이 끝날 때 컨텍스트 리셋

    def visit_Call(self, node):
        callee = self.get_callee(node)
        if callee:
            if callee not in self.builtin_modules:
                # 현재 클래스와 메서드 정보를 기반으로 호출자(caller) 식별
                if self.current_class and self.current_method:
                    caller = f"{get_module_path(self.current_file)}.{self.current_class}.{self.current_method}"
                elif self.current_class:
                    caller = f"{get_module_path(self.current_file)}.{self.current_class}"
                else:
                    # 파일의 전역 스코프에서의 호출은 GlobalScope 표기 대신 파일 경로 기반으로 기록
                    caller = f"{get_module_path(self.current_file)}"

                # imports 매핑을 사용하여 callee의 모듈 경로 변환
                parts = callee.split(".")
                if parts[0] in self.imports:
                    parts[0] = self.imports[parts[0]]
                    callee = ".".join(parts)

                    self.call_info.add_call(caller, callee)
        self.generic_visit(node)

    def get_callee(self, node):
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            return f"{node.func.value.id}.{node.func.attr}"
        elif isinstance(node.func, ast.Name):
            return node.func.id
        return None


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
    return call_info.call_relations


def load_config():
    default_settings = {
        "ignore_list": ["__pycache__", ".git", ".venv", "venv", "env", "alembic"],
        "third_party_modules": [],
        "path": ".",
    }

    try:
        settings = default_settings.copy()
        with open("pyproject.toml", "r", encoding="utf-8") as toml_file:
            config = toml.load(toml_file)
        settings["ignore_list"] += config.get("tool", {}).get("py-flow-trace", {}).get("ignore", [])
        settings["path"] = config.get("tool", {}).get("py-flow-trace", {}).get("path", ".")
        settings["third_party_modules"] = config.get("tool", {}).get("py-flow-trace", {}).get("third_party_modules", [])
        return settings
    except FileNotFoundError:
        return default_settings


settings = load_config()
call_relations = walk_and_analyze(settings["path"], settings["ignore_list"])

with open("analysis_result.json", "w") as json_file:
    # defaultdict를 일반 dict로 변환
    json_data = {caller: dict(callees) for caller, callees in call_relations.items()}
    json.dump(json_data, json_file, indent=4)


# make template.html
html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Call Relations Visualization</title>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/d3-sankey/0.12.3/d3-sankey.min.js"></script>

    <style>
        .node rect {{
            cursor: move;
            fill-opacity: .9;
            shape-rendering: crispEdges;
        }}
        .node text {{
            pointer-events: none;
            text-shadow: 0 1px 0 #fff;
        }}
        .link {{
            fill: none;
            stroke: #000;
            stroke-opacity: .2;
        }}
        .link:hover {{
            stroke-opacity: .5;
        }}
    </style>
</head>
<body>
    <svg width="3600" height="1100"></svg>
    <script>
        const data = {json_data};
        var sankeyData = {{
            nodes: [],
            links: []
        }};

        // 노드 이름을 추적하기 위한 임시 맵
        let nodeMap = {{}};

        // 노드를 만들고 맵에 추가하는 함수
        function getOrCreateNode(name) {{
            if (!nodeMap.hasOwnProperty(name)) {{
                nodeMap[name] = {{
                name: name,
                nodeIndex: sankeyData.nodes.length
                }};
                sankeyData.nodes.push({{ name: name }});
            }}
            return nodeMap[name].nodeIndex;
        }}

        // 원본 데이터를 Sankey 데이터 형식으로 변환
        for (let caller in data) {{
            for (let callee in data[caller]) {{
                var sourceIndex = getOrCreateNode(caller);
                var targetIndex = getOrCreateNode(callee);
                var value = data[caller][callee];

                sankeyData.links.push({{
                source: sourceIndex,
                target: targetIndex,
                value: value
                }});
            }}
        }}

        var svg = d3.select("svg"),
            width = +svg.attr("width"),
            height = +svg.attr("height");

        var formatNumber = d3.format(",.0f"),
            format = function(d) {{ return formatNumber(d) + " TWh"; }},
            color = d3.scaleOrdinal(d3.schemeCategory10);

        var sankey = d3.sankey()
            .nodeWidth(15)
            .nodePadding(10)
            .extent([[1, 1], [width - 1, height - 5]]);

        var path = sankey.links();

        sankey(sankeyData);

        var link = svg.append("g")
            .selectAll(".link")
            .data(sankeyData.links)
            .enter().append("path")
              .attr("class", "link")
              .attr("d", path)
              .style("stroke-width", function(d) {{ return Math.max(1, d.width); }})
              .sort(function(a, b) {{ return b.width - a.width; }});

        link.append("title")
            .text(function(d) {{ return d.source.name + " → " + d.target.name + "\\n" + format(d.value); }});

        var node = svg.append("g")
            .selectAll(".node")
            .data(sankeyData.nodes)
            .enter().append("g")
              .attr("class", "node")
              .attr("transform", function(d) {{ return "translate(" + d.x0 + "," + d.y0 + ")"; }})
              .call(d3.drag()
                  .subject(function(d) {{ return d; }})
                  .on("start", function() {{ this.parentNode.appendChild(this); }})
                  .on("drag", dragmove));

        node.append("rect")
            .attr("height", function(d) {{ return d.y1 - d.y0; }})
            .attr("width", sankey.nodeWidth())
            .style("fill", function(d) {{ return d.color = color(d.name.replace(/ .*/, "")); }})
            .style("stroke", function(d) {{ return d3.rgb(d.color).darker(2); }})
            .append("title")
            .text(function(d) {{ return d.name + "\\n" + format(d.value); }});

        node.append("text")
            .attr("x", -6)
            .attr("y", function(d) {{ return (d.y1 - d.y0) / 2; }})
            .attr("dy", "0.35em")
            .attr("text-anchor", "end")
            .text(function(d) {{ return d.name; }})
            .filter(function(d) {{ return d.x0 < width / 2; }})
            .attr("x", 6 + sankey.nodeWidth())
            .attr("text-anchor", "start");
            // dragmove function to enable node dragging
        function dragmove(d) {{
            var rectY = d3.event.y;
            var rectX = d3.event.x;

            d3.select(this)
            .attr("transform", "translate("
                + rectX + ","
                + (d.y0 = Math.max(
                    0, Math.min(height - (d.y1 - d.y0), rectY))) + ")");

            sankey.update(sankeyData);
            link.attr("d", path);
        }}
    </script>
</body>
</html>
"""

with open("template.html", "w") as html_file:
    html_file.write(html)

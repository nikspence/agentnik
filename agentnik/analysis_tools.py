"""Pure bounded numeric tools: no eval, imports, filesystem, or network execution."""
import ast
import csv
import io
import json
import math
import operator
import statistics


class AnalysisError(ValueError):
    pass


def finite(value):
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e100:
        raise AnalysisError('Result is non-finite or exceeds magnitude 1e100.')
    return value


def calculate(expression):
    if not isinstance(expression, str) or not 0 < len(expression) <= 1000:
        raise AnalysisError('Expression must contain 1–1000 characters.')
    ops = {ast.Add:operator.add, ast.Sub:operator.sub, ast.Mult:operator.mul, ast.Div:operator.truediv, ast.FloorDiv:operator.floordiv, ast.Mod:operator.mod, ast.Pow:operator.pow}
    funcs = {'abs':abs, 'round':round, 'min':min, 'max':max, 'sqrt':math.sqrt, 'log':math.log, 'log10':math.log10, 'sin':math.sin, 'cos':math.cos, 'tan':math.tan, 'ceil':math.ceil, 'floor':math.floor}
    try:
        tree = ast.parse(expression, mode='eval')
        if sum(1 for _ in ast.walk(tree)) > 120: raise AnalysisError('Expression is too complex.')
        def visit(node, depth=0):
            if depth > 20: raise AnalysisError('Expression nesting exceeds 20.')
            if isinstance(node, ast.Constant): return finite(node.value)
            if isinstance(node, ast.Name) and node.id in ('pi', 'e'): return getattr(math, node.id)
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                value = visit(node.operand, depth+1); return finite(-value if isinstance(node.op, ast.USub) else value)
            if isinstance(node, ast.BinOp) and type(node.op) in ops:
                left, right = visit(node.left, depth+1), visit(node.right, depth+1)
                if isinstance(node.op, ast.Pow) and abs(right) > 100: raise AnalysisError('Exponent magnitude exceeds 100.')
                return finite(ops[type(node.op)](left, right))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in funcs and not node.keywords and 1 <= len(node.args) <= 20:
                return finite(funcs[node.func.id](*[visit(arg, depth+1) for arg in node.args]))
            raise AnalysisError('Only numeric arithmetic and documented math functions are allowed.')
        return {'expression':expression, 'value':visit(tree.body), 'precision':'Python integer / IEEE-754 float; approximate for non-integer arithmetic'}
    except AnalysisError: raise
    except (ValueError, TypeError, ArithmeticError, SyntaxError, RecursionError):
        raise AnalysisError('Invalid arithmetic, function arguments, or numeric domain.') from None


def analyze_data(data):
    """data is a JSON request containing format, content, optional group_by."""
    if not isinstance(data, str) or len(data.encode()) > 16000: raise AnalysisError('Data request exceeds 16 KB.')
    try:
        request = json.loads(data)
        if not isinstance(request, dict) or set(request) - {'format','content','group_by'} or not {'format','content'} <= set(request): raise AnalysisError('Use format, content, and optional group_by.')
        content = request['content']; kind = request['format']
        if not isinstance(content, str): raise AnalysisError('content must be a string.')
        if kind == 'csv':
            reader = csv.reader(io.StringIO(content)); headers = next(reader, [])
            if not headers or len(headers) > 32 or len(set(headers)) != len(headers) or any(not h or len(h)>100 for h in headers): raise AnalysisError('CSV requires 1–32 unique nonempty column headers (up to 100 characters).')
            rows = []
            for values in reader:
                if len(values) != len(headers): raise AnalysisError('CSV row width does not match headers.')
                rows.append(dict(zip(headers, values)))
                if len(rows)>1000: raise AnalysisError('At most 1000 rows are supported.')
        elif kind == 'json':
            rows = json.loads(content)
            if not isinstance(rows,list) or not rows or len(rows)>1000 or any(not isinstance(r,dict) for r in rows): raise AnalysisError('JSON content must be 1–1000 row objects.')
            headers = list(dict.fromkeys(key for row in rows for key in row))
            if not 1<=len(headers)<=32 or any(not key or len(key)>100 for key in headers): raise AnalysisError('Use 1–32 nonempty column names (up to 100 characters).')
            if any(type(v) not in (str,int,float,bool,type(None)) for row in rows for v in row.values()): raise AnalysisError('Nested JSON cells are not supported.')
        else: raise AnalysisError('format must be csv or json.')
        if not rows: raise AnalysisError('No data rows.')
        def summary(selected):
            result = {}
            for column in headers:
                numbers=[];missing=other=0
                for row in selected:
                    value=row.get(column)
                    if value is None or isinstance(value,str) and not value.strip(): missing+=1;continue
                    try:
                        if isinstance(value,bool):raise ValueError()
                        number=float(value)
                        if not math.isfinite(number) or abs(number)>1e100:raise ValueError()
                        numbers.append(number)
                    except (ValueError,TypeError,OverflowError):other+=1
                item={'numeric_count':len(numbers),'missing_count':missing,'nonnumeric_count':other}
                if numbers:
                    item.update(min=min(numbers),max=max(numbers),sum=math.fsum(numbers),mean=statistics.fmean(numbers),median=statistics.median(numbers),sample_stdev=statistics.stdev(numbers) if len(numbers)>1 else None)
                result[column]=item
            return result
        result={'rows':len(rows),'columns':summary(rows),'notice':'Statistics use finite numeric cells only; booleans and invalid numbers count as nonnumeric. Missing cells are excluded. Float arithmetic is approximate.'}
        if 'group_by' in request:
            column=request['group_by']
            if not isinstance(column,str) or column not in headers:raise AnalysisError('group_by must name an existing column.')
            groups={}
            for row in rows:
                value=row.get(column); key=json.dumps(value,ensure_ascii=False,allow_nan=False)
                groups.setdefault(key,[]).append(row)
                if len(groups)>10:raise AnalysisError('Grouping supports at most 10 distinct values.')
            result['groups']=[{'value':json.loads(key),'rows':len(selected),'columns':summary(selected)} for key,selected in groups.items()]
        if len(json.dumps(result,allow_nan=False).encode())>24000:raise AnalysisError('Analysis output exceeds 24 KB; select fewer columns or groups.')
        return result
    except AnalysisError:raise
    except (ValueError,TypeError,OverflowError,csv.Error,RecursionError):raise AnalysisError('Invalid CSV/JSON data request.') from None


HANDLERS={'calculate':calculate,'analyze_data':analyze_data}

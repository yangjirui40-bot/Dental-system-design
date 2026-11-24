from datetime import datetime, date, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from .security import require

def timestamp(value):
    value=datetime.fromisoformat(str(value).replace('Z','+00:00')) if not isinstance(value,datetime) else value
    require(value.tzinfo is not None,'时点必须包含时区')
    return value

def money(value):
    try: result=Decimal(str(value));require(result.is_finite(),'金额必须有限')
    except InvalidOperation: require(False,'金额格式错误')
    require(result>=0,'金额不能为负')
    return result.quantize(Decimal('.01'),rounding=ROUND_HALF_UP)

def acyclic(nodes, edges):
    graph={n:[] for n in nodes}
    for a,b in edges:
        require(a in graph and b in graph,'阶段关系端点必须属于本版计划')
        require(a!=b,'阶段不能依赖自身');graph[a].append(b)
    seen=set();active=set()
    def visit(n):
        require(n not in active,'阶段先决关系形成循环')
        if n in seen:return
        active.add(n)
        for b in graph[n]:visit(b)
        active.remove(n);seen.add(n)
    for n in nodes:visit(n)

def version(row, body):
    require(row,'业务记录不存在',404)
    if 'row_version' in row:require(int(body.get('row_version',-1))==row['row_version'],'资料已被其他操作更新，请刷新',409)

def split_cost(amount, allocations):
    require(allocations,'至少填写一项费用分摊')
    require(sum((money(a['allocated_amount']) for a in allocations),Decimal(0))==money(amount),'分摊合计必须等于费用来源金额')

def aggregate_fund(profits):
    total=sum((Decimal(str(n)) for n in profits),Decimal(0))
    return total,max(total,Decimal(0))*Decimal('.10')

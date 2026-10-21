"""Deterministic language/physical-context generator. No numeric hidden truth."""
import random
import re
import unicodedata

DOMAINS = {
    "dispatch": {
        "description": "车队正在比较几种当日安排。下面是现场记录，可能有些记录与选择无关。",
        "catalog": [
            {"id": "transfer_work", "label": "Transfer workload", "measure": "货箱改由另一辆车运送的次数"},
            {"id": "thermal_hold", "label": "Thermal holding", "measure": "货物停在低温区域的时段数"},
            {"id": "return_travel", "label": "Return travel", "measure": "车辆卸货后还需行驶的路段数"},
        ],
        "symptoms": [
            ["箱子每多转到一辆车上，下一站就又晚一阵，班末还得重对单据。",
             "东西来回挪过几辆车后，记录总要重新核一遍，后面的人等得不耐烦。"],
            ["东西在那间很冷的屋子里放得越久，设备表上的读数涨得越快。",
             "货物一直没从冷房搬走，压缩机响了好几个时段，值班人又去看电表。"],
            ["东西送完了，司机还要开很远才能回去，大家说油和时间都耗在后半程。",
             "卸完东西并不算结束，有几台车又跑了好几段空路才回到起点。"],
        ],
        "incidental": [
            ["今天有些箱子改放到另一辆车，现场提醒大家看一下封签。",
             "几辆车旁的货箱需要挪动，负责人把号码念了一遍。"],
            ["低温区域今天也有货，值班表上记了进出时段。",
             "有人核对冷房里还有哪些货，门边夹着进出记录。"],
            ["派车表还标了卸货之后的路线，调度员提了一句路况。",
             "司机在图上画了回程经过的几个路段。"],
        ],
        "chatter": ["午饭的汤比昨天咸。", "休息室窗边的盆栽长了新叶子。"],
    },
    "staffing": {
        "description": "服务站正在比较几种当天人员安排。下面是现场记录，可能有些记录与选择无关。",
        "catalog": [
            {"id": "successive_duty", "label": "Successive duty", "measure": "连续值守而未休息的额外时段数"},
            {"id": "station_crossing", "label": "Station crossing", "measure": "人员从一个服务点走到另一个服务点的次数"},
            {"id": "task_transition", "label": "Task transition", "measure": "人员改做不同类别事项的次数"},
        ],
        "symptoms": [
            ["几段活连着干，中间一直没停，后面填表时错字明显多了。",
             "从开工接着干到后来还没歇，几个同事揉眼睛，返工又拖了一阵。"],
            ["一会儿去东边一会儿去西边，人还在路上，窗口前已经有人等。",
             "刚在这边坐下又被叫到另一边，走来走去占掉不少接待时间。"],
            ["刚熟悉手里的表，又改用另一套做法，重新找说明耽误了后面的事。",
             "手上的事情换了类别，大家得重看规则，熟练起来之前一直出小错。"],
        ],
        "incidental": [
            ["排班纸上标了几段连着的工作，负责人让大家看清顺序。",
             "值班表里有连续的格子，旁边写了人员名字。"],
            ["两处窗口都有人，墙上贴着从这边去那边的方向。",
             "有人提醒新同事另一处服务点在哪个门后面。"],
            ["今天要处理几类表，桌上放着对应的说明。",
             "清单上分了不同类别的事情，负责人把纸整理好。"],
        ],
        "chatter": ["茶水间的杯子换了新图案。", "有人说周末想去看一场电影。"],
    },
    "workshop": {
        "description": "车间正在比较几种当日加工安排。下面是现场记录，可能有些记录与选择无关。",
        "catalog": [
            {"id": "setup_change", "label": "Setup change", "measure": "设备拆下旧夹具并装上另一套夹具的次数"},
            {"id": "warmup_cycle", "label": "Warmup cycle", "measure": "设备从冷机重新启动的次数"},
            {"id": "material_distance", "label": "Material distance", "measure": "原料在工作台之间经过的路段数"},
        ],
        "symptoms": [
            ["刚拧紧这套东西又得卸下换另一套，机器停着，师傅一直在旁边忙。",
             "不同批次轮着来，固定零件的那套装置反复拆装，等开工的人又排起来。"],
            ["关掉再开后，前面一阵总做不了东西，电表却还在走。",
             "机器凉下来以后再启动，要等好久才能接着做，师傅又看了看耗电记录。"],
            ["料从这张台子绕到那张台子，小车来回跑，后一道工序老在等。",
             "东西要经过好几个地方才送到手边，搬的人走了不少路，机器还空着。"],
        ],
        "incidental": [
            ["今天用到几套固定零件的装置，师傅核对了架子上的编号。",
             "工作单旁边写了装置编号，准备时有人逐项念过。"],
            ["值班人记录了今天开机和关机的次数。",
             "开关机记录夹在设备旁边，班长翻看了一下。"],
            ["桌边画了原料经过哪些台子的路线。",
             "小车停放的位置和运送路线已经写到板上。"],
        ],
        "chatter": ["门口的小猫又睡在纸箱里。", "有人说今天带的水果特别甜。"],
    },
}

FORBIDDEN = [
    "唯一", "真因子", "真实原因", "真实权重", "正确答案", "标准答案",
    "干扰因子", "干扰项", "零成本", "权重为零", "hiddenTruth", "trueRegret",
    "dangerThreshold", "truth", "oracle", "hypotheses", "ground_truth",
]


def normalized(text):
    return unicodedata.normalize("NFKC", text).casefold()


def tokens(text):
    # Unicode words, with identifier separators broken out explicitly.
    return set(re.findall(r"[a-z0-9]+|[\u3400-\u9fff]+", normalized(text)))


def check_no_leak(public, catalog, truth_keys):
    text = "\n".join([public["description"], *public["logs"]])
    folded = normalized(text)
    identifiers = [str(h[k]) for h in catalog for k in ("id", "label")] + list(truth_keys)
    leaked = [word for word in [*identifiers, *FORBIDDEN] if normalized(word) in folded]
    if leaked:
        raise ValueError("Language leakage: forbidden words " + repr(sorted(set(leaked))))
    structure = set().union(*(tokens(w) for w in identifiers))
    overlap = sorted(structure & tokens(text))
    if overlap:
        raise ValueError("Language leakage: structure token " + repr(overlap[0]))
    return {"passed": True, "structureTokens": sorted(structure), "intersection": []}


def generate(domain, seed):
    spec = DOMAINS[domain]
    code = {"dispatch": 13, "staffing": 29, "workshop": 47}[domain]
    rng = random.Random(seed * 101 + code)
    # Phenomenological role, not a numeric coefficient. External evaluator
    # alone assigns nonzero weight and generates bounded-noise observations.
    active = rng.randrange(3)
    logs = [rng.choice(spec["symptoms"][j] if j == active else spec["incidental"][j])
            for j in range(3)]
    logs.append(rng.choice(spec["chatter"]))
    rng.shuffle(logs)
    catalog = [{**h, "monitor": f"m{j}"} for j, h in enumerate(spec["catalog"])]
    rng.shuffle(catalog)
    contexts = []
    for k in range(7):  # six histories, one untouched deployment context
        contexts.append({
            "id": f"context-{k}",
            "actions": [
                {"id": f"p{a}", "knownCostTenths": rng.randint(0, 40),
                 "monitors": {h["id"]: rng.randint(0, 3) for h in spec["catalog"]}}
                for a in range(4)
            ],
        })
    public = {"description": spec["description"], "logs": logs, "catalog": catalog}
    keys = [h["id"] for h in spec["catalog"]]
    check = check_no_leak(public, catalog, keys)
    return {"id": f"{domain}-s{seed}", "domain": domain, "seed": seed,
            "public": public, "contexts": contexts, "leakCheck": check,
            "design": {"phenomenonIndex": active, "factorIds": keys, "domainCode": code}}


def inventory():
    formal = [{"domain": domain, "seed": seed} for domain in DOMAINS for seed in range(81001, 81021)]
    random.Random(81000001).shuffle(formal)
    pilots = [{"domain": "dispatch", "seed": 80001}, {"domain": "staffing", "seed": 80002}]
    return pilots, formal


def signed_event_rule(logs, dictionary):
    """Frozen text-only baseline: qualitative event constraints, exact nullspace.

    The caller supplies just logs and atom definitions. This function never reads
    truth, filenames, histories, seeds or generator state. It does not enumerate
    a list of candidate answers. Unknown syntax or ambiguity is a retained error.
    """
    from fractions import Fraction as Q
    from math import gcd, lcm

    names = [atom["id"] for atom in dictionary]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate dictionary atom")
    zero_rows, directional_rows = [], []
    for raw in logs:
        # An explicitly withdrawn utterance is not an observation. Retain the
        # original raw string for provenance; parsing changes no evidence.
        observation = raw.split("此前有人说", 1)[0]
        if "；" not in observation:
            raise ValueError("No event/outcome boundary")
        event_text, consequence = observation.split("；", 1)
        if "其余记录未变" not in consequence:
            raise ValueError("Uncontrolled event comparison")
        neutral = "相同" in consequence or "没有变化" in consequence
        up, down = "增加" in consequence, "减少" in consequence
        if sum((neutral, up, down)) != 1:
            raise ValueError("Ambiguous qualitative consequence")
        vector = [Q(0) for _ in names]
        for j, atom in enumerate(dictionary):
            label = re.escape(atom["measurement"])
            forward = re.search(label + r"(发生了|新增|撤回)([1-9][0-9]*)次", event_text)
            backward = re.search(r"([1-9][0-9]*)次" + label, event_text)
            if forward and backward:
                raise ValueError("Repeated event mention")
            if forward:
                vector[j] = Q(forward.group(2)) * (-1 if forward.group(1) == "撤回" else 1)
            elif backward:
                vector[j] = Q(backward.group(1)) * (-1 if "撤销" in event_text else 1)
            elif atom["measurement"] in event_text:
                raise ValueError("Unparsed named event")
        if not any(vector):
            raise ValueError("No parsed event")
        if neutral:
            zero_rows.append(vector)
        else:
            directional_rows.append((vector, 1 if up else -1))

    # Gaussian elimination of linguistic invariances, not numeric histories.
    matrix = [row.copy() for row in zero_rows]
    pivots, r = [], 0
    for col in range(len(names)):
        pivot = next((k for k in range(r, len(matrix)) if matrix[k][col]), None)
        if pivot is None:
            continue
        matrix[r], matrix[pivot] = matrix[pivot], matrix[r]
        scale = matrix[r][col]
        matrix[r] = [v / scale for v in matrix[r]]
        for k in range(len(matrix)):
            if k != r and matrix[k][col]:
                factor = matrix[k][col]
                matrix[k] = [v - factor * p for v, p in zip(matrix[k], matrix[r])]
        pivots.append(col)
        r += 1
    free = [col for col in range(len(names)) if col not in pivots]
    if len(free) != 1 or not directional_rows:
        raise ValueError("Text does not identify one signed ray")
    vector = [Q(0) for _ in names]
    vector[free[0]] = Q(1)
    for k, col in enumerate(pivots):
        vector[col] = -matrix[k][free[0]]
    signs = []
    for row, direction in directional_rows:
        value = sum(a * b for a, b in zip(row, vector))
        if not value:
            raise ValueError("Direction contradicts invariances")
        signs.append(direction * (1 if value > 0 else -1))
    if len(set(signs)) != 1:
        raise ValueError("Conflicting directions")
    den = lcm(*(v.denominator for v in vector))
    integers = [int(v * den) * signs[0] for v in vector]
    common = gcd(*integers)
    terms = {name: value // common for name, value in zip(names, integers) if value}
    if len(terms) != 2 or len({1 if v > 0 else -1 for v in terms.values()}) != 2:
        raise ValueError("Constructed structure is not an opposite-sign pair")
    return {"hypotheses": [{"id": "constructed", "terms": terms, "source": "\n".join(logs)}]}

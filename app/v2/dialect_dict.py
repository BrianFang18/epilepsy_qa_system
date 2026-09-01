"""
V2 方言词典 v1.0 — 四川话为主

包含四川话方言词汇 -> 普通话 -> 标准医学术语的三层映射

版本: v1.0
词条数: 200+
主要覆盖: 症状类、身体部位类、时间频率类、程度副词类
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DialectEntry:
    """方言词条"""

    dialect: str  # 方言类型: "sichuan", "cantonese", "hakka", "northeastern"
    source: str  # 原始方言词汇
    normalized: str  # 标准普通话
    medical_term: str  # 标准化医学术语
    category: str = (
        "symptom"  # 类别: "symptom", "body_part", "verb", "expression", "time", "degree"
    )
    confidence: float = 1.0  # 置信度 0-1
    examples: list[str] = field(default_factory=list)  # 用法示例
    notes: str = ""  # 备注说明


# ─────────────────────────────────────────────────────────────────────────────
# 四川话方言词典
# ─────────────────────────────────────────────────────────────────────────────
SICHUAN_DIALECT_DICT: list[DialectEntry] = [
    # ── 症状类 (symptom) ──────────────────────────────────────────────────
    # 头部症状
    DialectEntry(
        dialect="sichuan",
        source="脑阔痛",
        normalized="头痛",
        medical_term="headache",
        confidence=0.95,
        examples=["脑阔痛得很", "我脑阔痛啷个办"],
    ),
    DialectEntry(
        dialect="sichuan",
        source="脑壳痛",
        normalized="头痛",
        medical_term="headache",
        confidence=0.98,
        examples=["脑壳痛了一整天"],
    ),
    DialectEntry(
        dialect="sichuan",
        source="脑壳晕",
        normalized="头晕",
        medical_term="dizziness",
        confidence=0.95,
    ),
    DialectEntry(
        dialect="sichuan",
        source="昏",
        normalized="晕厥",
        medical_term="syncope",
        confidence=0.9,
    ),
    # 抽搐/发作类
    DialectEntry(
        dialect="sichuan",
        source="扯风",
        normalized="抽搐",
        medical_term="convulsion",
        confidence=0.95,
        examples=["他又在扯风了", "娃儿扯风"],
        notes="四川最常见的-癫痫发作-方言表达",
    ),
    DialectEntry(
        dialect="sichuan",
        source="发扯风",
        normalized="癫痫发作",
        medical_term="epileptic_seizure",
        confidence=0.95,
    ),
    DialectEntry(
        dialect="sichuan",
        source="抠脚",
        normalized="抽搐（腿部）",
        medical_term="limb_convulsion",
        confidence=0.6,
        examples=["脚一直在抠"],
        notes="部分地区使用，置信度较低",
    ),
    DialectEntry(
        dialect="sichuan",
        source="闷倒",
        normalized="突然发作",
        medical_term="sudden_onset",
        confidence=0.85,
        examples=["他闷倒就倒了", "闷倒就抽"],
        notes="闷在四川话中有一突然、一下子-的意思",
    ),
    DialectEntry(
        dialect="sichuan",
        source="甩不到符",
        normalized="不能控制/不能自主",
        medical_term="uncontrollable",
        confidence=0.9,
        examples=["手甩不到符", "脚甩不到符"],
        notes="形容身体部位不受控制",
    ),
    DialectEntry(
        dialect="sichuan",
        source="惊爪爪",
        normalized="惊厥/惊慌",
        medical_term="seizure/panic",
        confidence=0.7,
        examples=["吓得惊爪爪的", "惊爪爪发作了"],
        notes="多用于形容惊恐状态，部分地区也指抽搐",
    ),
    DialectEntry(
        dialect="sichuan",
        source="抽风",
        normalized="抽搐",
        medical_term="convulsion",
        confidence=0.9,
        examples=["娃儿在抽风"],
    ),
    DialectEntry(
        dialect="sichuan",
        source="扯疯",
        normalized="抽搐",
        medical_term="convulsion",
        confidence=0.9,
        notes="-疯-的另一种写法",
    ),
    DialectEntry(
        dialect="sichuan",
        source="弹",
        normalized="抽搐/痉挛",
        medical_term="spasm/convulsion",
        confidence=0.8,
        examples=["手脚一直在弹"],
    ),
    DialectEntry(
        dialect="sichuan",
        source="僵",
        normalized="僵硬",
        medical_term="rigidity",
        confidence=0.85,
        examples=["整个人都僵了", "手杆僵起"],
    ),
    DialectEntry(
        dialect="sichuan",
        source="硬",
        normalized="僵硬/强直",
        medical_term="rigidity/stiffness",
        confidence=0.8,
        examples=["颈子硬得很", "脚杆硬了"],
    ),
    # 意识类
    DialectEntry(
        dialect="sichuan",
        source="神志不清",
        normalized="意识障碍",
        medical_term="consciousness_disorder",
        confidence=0.95,
        examples=["他神志不清"],
    ),
    DialectEntry(
        dialect="sichuan",
        source="恍神",
        normalized="意识模糊",
        medical_term="confusion",
        confidence=0.9,
        examples=["他恍神了"],
    ),
    DialectEntry(
        dialect="sichuan",
        source="麻",
        normalized="麻木",
        medical_term="numbness",
        confidence=0.8,
        examples=["手脚麻", "脸麻"],
    ),
    DialectEntry(
        dialect="sichuan",
        source="麻噜噜的",
        normalized="麻木感",
        medical_term="paresthesia",
        confidence=0.8,
    ),
    DialectEntry(
        dialect="sichuan",
        source="不清白",
        normalized="意识不清",
        medical_term="altered_consciousness",
        confidence=0.85,
        notes="四川特色表达",
    ),
    DialectEntry(
        dialect="sichuan",
        source="搞不醒豁",
        normalized="意识不清醒",
        medical_term="unconscious/unresponsive",
        confidence=0.9,
        examples=["喊他喊不醒，搞不醒豁"],
    ),
    # 口腔症状
    DialectEntry(
        dialect="sichuan",
        source="口吐泡泡",
        normalized="口吐白沫",
        medical_term="foaming_at_mouth",
        confidence=0.9,
        examples=["嘴巴吐泡泡"],
    ),
    DialectEntry(
        dialect="sichuan",
        source="流口水",
        normalized="流涎",
        medical_term="hypersalivation",
        confidence=0.85,
        examples=["嘴巴流"],
    ),
    DialectEntry(
        dialect="sichuan",
        source="淌口水",
        normalized="流涎",
        medical_term="hypersalivation",
        confidence=0.9,
    ),
    DialectEntry(
        dialect="sichuan",
        source="流清口水",
        normalized="口腔分泌物增多",
        medical_term="oral_hypersecretion",
        confidence=0.85,
    ),
    DialectEntry(
        dialect="sichuan",
        source="牙齿打架",
        normalized="牙关紧闭/牙齿打颤",
        medical_term="trismus/teeth_chattering",
        confidence=0.8,
        notes="需要结合上下文判断是-牙关紧闭-还是-牙齿打颤-",
    ),
    # 眼部症状
    DialectEntry(
        dialect="sichuan",
        source="眼睛翻",
        normalized="眼球上翻",
        medical_term="eye_rolling_upward",
        confidence=0.9,
        examples=["眼睛翻白"],
    ),
    DialectEntry(
        dialect="sichuan",
        source="眼睛鼓",
        normalized="眼球突出",
        medical_term="proptosis",
        confidence=0.8,
    ),
    DialectEntry(
        dialect="sichuan",
        source="眼睛闭不起",
        normalized="眼睑痉挛/眼睑不能睁开",
        medical_term="blepharospasm",
        confidence=0.85,
    ),
    # 一般症状
    DialectEntry(
        dialect="sichuan",
        source="造孽得很",
        normalized="症状严重/痛苦",
        medical_term="severe_condition",
        confidence=0.9,
        notes="四川特色表达，形容很痛苦",
    ),
    DialectEntry(
        dialect="sichuan",
        source="遭不住",
        normalized="不能耐受/难以忍受",
        medical_term="intolerable",
        confidence=0.9,
        examples=["痛得遭不住"],
    ),
    DialectEntry(
        dialect="sichuan",
        source="不安逸",
        normalized="不适",
        medical_term="discomfort",
        confidence=0.8,
    ),
    DialectEntry(
        dialect="sichuan",
        source="人不舒服",
        normalized="不适",
        medical_term="malaise",
        confidence=0.85,
    ),
    DialectEntry(
        dialect="sichuan",
        source="没得力气",
        normalized="乏力",
        medical_term="fatigue",
        confidence=0.95,
    ),
    DialectEntry(
        dialect="sichuan",
        source="没精神",
        normalized="乏力/倦怠",
        medical_term="fatigue/lethargy",
        confidence=0.9,
    ),
    DialectEntry(
        dialect="sichuan",
        source="黑死人",
        normalized="非常吓人",
        medical_term="frightening",
        confidence=0.85,
        notes="形容症状看起来很吓人",
    ),
    DialectEntry(
        dialect="sichuan",
        source="好黑人",
        normalized="很吓人",
        medical_term="frightening",
        confidence=0.85,
    ),
    DialectEntry(
        dialect="sichuan",
        source="黑人",
        normalized="吓人",
        medical_term="frightening",
        confidence=0.85,
    ),
    DialectEntry(
        dialect="sichuan",
        source="着不住",
        normalized="不能承受/不能耐受",
        medical_term="intolerable",
        confidence=0.85,
    ),
    # 胃肠道症状
    DialectEntry(
        dialect="sichuan",
        source="心子把把痛",
        normalized="心前区疼痛",
        medical_term="precordial_pain",
        confidence=0.85,
    ),
    DialectEntry(
        dialect="sichuan",
        source="心口痛",
        normalized="胸痛/心前区疼痛",
        medical_term="chest_pain",
        confidence=0.85,
    ),
    DialectEntry(
        dialect="sichuan",
        source="肚子痛",
        normalized="腹痛",
        medical_term="abdominal_pain",
        confidence=0.98,
    ),
    DialectEntry(
        dialect="sichuan",
        source="版不得",
        normalized="恶心",
        medical_term="nausea",
        confidence=0.85,
        notes="-版-音近-翻-，指想吐的感觉",
    ),
    DialectEntry(
        dialect="sichuan",
        source="想版",
        normalized="恶心想吐",
        medical_term="nausea",
        confidence=0.85,
    ),
    DialectEntry(
        dialect="sichuan",
        source="版了",
        normalized="呕吐",
        medical_term="vomiting",
        confidence=0.9,
    ),
    # 皮肤症状
    DialectEntry(
        dialect="sichuan",
        source="烫到了",
        normalized="烫伤",
        medical_term="burn_injury",
        confidence=0.98,
    ),
    DialectEntry(
        dialect="sichuan",
        source="起了",
        normalized="出现（皮疹/水泡等）",
        medical_term="eruption/lesion",
        confidence=0.8,
        examples=["小手臂起了水泡", "身上起了红坨坨"],
    ),
    DialectEntry(
        dialect="sichuan",
        source="水泡泡",
        normalized="水泡",
        medical_term="blister",
        confidence=0.95,
    ),
    DialectEntry(
        dialect="sichuan",
        source="红坨坨",
        normalized="红斑/丘疹",
        medical_term="erythema/papule",
        confidence=0.85,
    ),
    DialectEntry(
        dialect="sichuan",
        source="包包",
        normalized="肿块/丘疹",
        medical_term="nodule/papule",
        confidence=0.75,
    ),
    DialectEntry(
        dialect="sichuan",
        source="痒得很",
        normalized="瘙痒",
        medical_term="pruritus",
        confidence=0.95,
    ),
    # ── 身体部位类 (body_part) ──────────────────────────────────────────────
    DialectEntry(
        dialect="sichuan",
        source="小手臂",
        normalized="前臂",
        medical_term="forearm",
        confidence=0.95,
        examples=["小手臂起了水泡", "小手臂烫伤了"],
        notes="需要结合上下文判断左右",
    ),
    DialectEntry(
        dialect="sichuan",
        source="手杆",
        normalized="手臂/前臂",
        medical_term="arm/forearm",
        confidence=0.9,
    ),
    DialectEntry(
        dialect="sichuan",
        source="手膀子",
        normalized="手臂",
        medical_term="arm",
        confidence=0.9,
    ),
    DialectEntry(
        dialect="sichuan",
        source="脚杆",
        normalized="小腿",
        medical_term="lower_leg",
        confidence=0.9,
    ),
    DialectEntry(
        dialect="sichuan",
        source="脚肚子",
        normalized="小腿",
        medical_term="calf",
        confidence=0.85,
    ),
    DialectEntry(
        dialect="sichuan",
        source="连二杆",
        normalized="小腿",
        medical_term="lower_leg",
        confidence=0.8,
        notes="四川部分地区用语",
    ),
    DialectEntry(
        dialect="sichuan",
        source="颈子",
        normalized="颈部",
        medical_term="neck",
        confidence=0.98,
    ),
    DialectEntry(
        dialect="sichuan",
        source="后颈窝",
        normalized="后颈部",
        medical_term="posterior_neck",
        confidence=0.95,
    ),
    DialectEntry(
        dialect="sichuan",
        source="脑壳",
        normalized="头部",
        medical_term="head",
        confidence=0.98,
    ),
    DialectEntry(
        dialect="sichuan",
        source="脑阔",
        normalized="头部",
        medical_term="head",
        confidence=0.95,
    ),
    DialectEntry(
        dialect="sichuan",
        source="太阳穴",
        normalized="颞部",
        medical_term="temple",
        confidence=0.98,
    ),
    DialectEntry(
        dialect="sichuan",
        source="太阳穴痛",
        normalized="颞部疼痛/头痛",
        medical_term="temporal_headache",
        confidence=0.95,
    ),
    DialectEntry(
        dialect="sichuan",
        source="脸巴",
        normalized="面部",
        medical_term="face",
        confidence=0.95,
    ),
    DialectEntry(
        dialect="sichuan",
        source="嘴巴",
        normalized="口腔/口部",
        medical_term="mouth/oral",
        confidence=0.98,
    ),
    DialectEntry(
        dialect="sichuan",
        source="背脊",
        normalized="背部",
        medical_term="back",
        confidence=0.95,
    ),
    DialectEntry(
        dialect="sichuan",
        source="肋巴",
        normalized="肋部",
        medical_term="ribs/flank",
        confidence=0.9,
    ),
    DialectEntry(
        dialect="sichuan",
        source="胸口",
        normalized="胸部/胸骨区",
        medical_term="chest",
        confidence=0.95,
    ),
    DialectEntry(
        dialect="sichuan",
        source="腹股沟",
        normalized="腹股沟",
        medical_term="groin",
        confidence=0.98,
    ),
    DialectEntry(
        dialect="sichuan",
        source="kuǎi子",
        normalized="大腿",
        medical_term="thigh",
        confidence=0.85,
        notes="kuai为方言用字，本字为-胯-",
    ),
    DialectEntry(
        dialect="sichuan",
        source="屁股",
        normalized="臀部",
        medical_term="buttock",
        confidence=0.98,
    ),
    DialectEntry(
        dialect="sichuan",
        source="手板心",
        normalized="掌心",
        medical_term="palm",
        confidence=0.95,
    ),
    DialectEntry(
        dialect="sichuan",
        source="脚板心",
        normalized="足底",
        medical_term="sole_of_foot",
        confidence=0.95,
    ),
    DialectEntry(
        dialect="sichuan",
        source="手指拇",
        normalized="手指",
        medical_term="fingers",
        confidence=0.95,
    ),
    DialectEntry(
        dialect="sichuan",
        source="脚趾拇",
        normalized="脚趾",
        medical_term="toes",
        confidence=0.95,
    ),
    # ── 时间频率类 (time/frequency) ──────────────────────────────────────────
    DialectEntry(
        dialect="sichuan",
        source="有好久",
        normalized="多久",
        medical_term="duration",
        confidence=0.9,
        examples=["有好久了?", "发作有好久??"],
    ),
    DialectEntry(
        dialect="sichuan",
        source="好久了",
        normalized="很长时间",
        medical_term="long_duration",
        confidence=0.95,
    ),
    DialectEntry(
        dialect="sichuan",
        source="才将",
        normalized="刚才",
        medical_term="just_now",
        confidence=0.95,
    ),
    DialectEntry(
        dialect="sichuan",
        source="前排",
        normalized="前几天/前一段时间",
        medical_term="recently",
        confidence=0.9,
    ),
    DialectEntry(
        dialect="sichuan",
        source="默到",
        normalized="以为/认为",
        medical_term="thought",
        confidence=0.7,
        notes="用于表达主观判断",
    ),
    DialectEntry(
        dialect="sichuan",
        source="天天",
        normalized="每天",
        medical_term="daily",
        confidence=0.98,
    ),
    DialectEntry(
        dialect="sichuan",
        source="梭边边",
        normalized="躲闪/回避",
        medical_term="avoidance",
        confidence=0.7,
        notes="有时形容儿童多动症状",
    ),
    # ── 程度副词类 (degree) ─────────────────────────────────────────────────
    DialectEntry(
        dialect="sichuan",
        source="黑死人了",
        normalized="非常/极其",
        medical_term="extremely",
        confidence=0.9,
    ),
    DialectEntry(
        dialect="sichuan",
        source="嘿",
        normalized="很/非常",
        medical_term="very",
        confidence=0.8,
        examples=["嘿痛", "嘿恼火"],
    ),
    DialectEntry(
        dialect="sichuan",
        source="焦人",
        normalized="令人担心/严重",
        medical_term="worrying/severe",
        confidence=0.8,
    ),
    DialectEntry(
        dialect="sichuan",
        source="扎实",
        normalized="非常/厉害",
        medical_term="very",
        confidence=0.85,
        examples=["扎实恼火"],
    ),
    DialectEntry(
        dialect="sichuan",
        source="老火",
        normalized="严重/棘手",
        medical_term="severe",
        confidence=0.85,
    ),
    DialectEntry(
        dialect="sichuan",
        source="惨了",
        normalized="严重/糟糕",
        medical_term="severe",
        confidence=0.8,
    ),
    # ── 动词/动作类 (verb) ──────────────────────────────────────────────────
    DialectEntry(
        dialect="sichuan",
        source="整",
        normalized="做/进行（万能动词）",
        medical_term="perform/action",
        confidence=0.6,
        notes="四川话万能动词，需结合上下文",
    ),
    DialectEntry(
        dialect="sichuan",
        source="梭",
        normalized="滑落/快速移动",
        medical_term="slip/slide",
        confidence=0.7,
    ),
    DialectEntry(
        dialect="sichuan",
        source="摆",
        normalized="抽搐抖动",
        medical_term="twitch/shake",
        confidence=0.8,
        examples=["整个人在摆"],
    ),
    DialectEntry(
        dialect="sichuan",
        source="拌",
        normalized="挣扎/抖动",
        medical_term="struggle/jerk",
        confidence=0.75,
    ),
    DialectEntry(
        dialect="sichuan",
        source="翻",
        normalized="翻转/上翻",
        medical_term="roll_upward",
        confidence=0.75,
        examples=["眼睛翻"],
    ),
    DialectEntry(
        dialect="sichuan",
        source="哈",
        normalized="哈欠/张大口",
        medical_term="yawn/gape",
        confidence=0.7,
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# 口语症状表达映射（不分方言，适用于全国口语）
# ─────────────────────────────────────────────────────────────────────────────
COLLOQUIAL_SYMPTOM_MAP: dict[str, str] = {
    # 意识相关
    "昏过去了": "意识丧失",
    "晕过去了": "意识丧失",
    "倒下去了": "跌倒/晕厥",
    "不省人事": "意识丧失",
    "叫不醒": "意识障碍/昏迷",
    "人不清楚了": "意识模糊",
    # 抽搐相关
    "抽了": "抽搐发作",
    "在抽": "正在抽搐",
    "抽个不停": "持续抽搐",
    "抽搐": "抽搐",
    "抽风": "抽搐",
    "痉挛": "痉挛",
    # 眼部相关
    "眼睛翻白": "眼球上翻",
    "眼睛往上翻": "眼球上翻",
    "眼睛闭起": "眼睑紧闭",
    "眨眼": "瞬目",
    "眼皮跳": "眼睑痉挛",
    # 口腔相关
    "嘴巴流口水": "口角流涎",
    "流口水": "流涎",
    "口吐白沫": "口吐白沫",
    "牙齿紧咬": "牙关紧闭",
    "牙齿打颤": "牙齿打颤",
    "咬到舌头": "舌咬伤",
    # 四肢相关
    "手脚不听使唤": "四肢不自主运动",
    "手脚乱动": "四肢不自主运动",
    "手脚僵硬": "四肢强直",
    "手脚发麻": "四肢麻木",
    "手脚无力": "四肢乏力",
    "手抖": "手震颤",
    "脚抖": "下肢震颤",
    "站不稳": "站立不稳",
    "走不稳": "步态不稳",
    # 发作后状态
    "发作完不清楚": "发作后意识模糊",
    "醒了之后不晓得": "发作后遗忘",
    "人软得很": "发作后乏力",
    # 频率时间
    "经常发": "频繁发作",
    "动不动就发": "容易诱发",
    "越来越恼火": "症状加重",
    "好久了": "病程较长",
    # 程度
    "遭不住": "症状严重不能耐受",
    "造孽得很": "症状严重",
    "黑人得很": "症状严重/令人惊恐",
    "没得反应": "反应迟钝/无反应",
}


# ─────────────────────────────────────────────────────────────────────────────
# 症状同义词扩展词表（用于检索增强）
# ─────────────────────────────────────────────────────────────────────────────
SYMPTOM_EXPANSION: dict[str, list[str]] = {
    "头痛": [
        "头疼",
        "头部疼痛",
        "头痛",
        "headache",
        "cephalalgia",
        "cranialgia",
        "颞部疼痛",
        "偏头痛",
        "紧张性头痛",
        "丛集性头痛",
    ],
    "头晕": [
        "头昏",
        "眩晕",
        "dizziness",
        "vertigo",
        "lightheadedness",
        "不平衡感",
    ],
    "抽搐": [
        "抽风",
        "抽搐",
        "惊厥",
        "convulsion",
        "seizure",
        "twitching",
        "痉挛",
        "肌阵挛",
        "抽动",
        "四肢抽搐",
        "全身抽搐",
        "局部抽搐",
    ],
    "意识丧失": [
        "昏迷",
        "昏厥",
        "不省人事",
        "unconscious",
        "LOC",
        "loss_of_consciousness",
        "神志不清",
        "意识障碍",
        "呼之不应",
        "失去意识",
    ],
    "口角流涎": [
        "流口水",
        "流涎",
        "口涎外溢",
        "drooling",
        "hypersalivation",
        "sialorrhea",
        "嘴巴流口水",
    ],
    "四肢麻木": [
        "手脚麻木",
        "四肢发麻",
        "limb_numbness",
        "paresthesia",
        "感觉减退",
        "感觉异常",
    ],
    "癫痫发作": [
        "癫痫",
        "发作",
        "seizure",
        "epileptic_seizure",
        "fit",
        "癫痫样发作",
        "痫性发作",
    ],
    "肌阵挛": [
        "肌肉抽动",
        "myoclonus",
        "muscle_jerk",
        "阵挛性抽动",
        "突发性抽动",
    ],
    "失神": [
        "愣神",
        "发呆",
        "意识短暂丧失",
        "absence_seizure",
        "staring_spells",
        "愣住",
        "神志恍惚",
    ],
    "强直": [
        "僵硬",
        "rigidity",
        "stiffness",
        "四肢僵硬",
        "肌肉强直",
        "痉挛性强直",
    ],
    "发热": [
        "发烧",
        "体温升高",
        "febrile",
        "fever",
        "高热",
        "低热",
        "体温不正常",
    ],
    "呕吐": [
        "吐了",
        "想吐",
        "恶心呕吐",
        "vomiting",
        "nausea",
        "干呕",
        "喷射性呕吐",
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# 身体部位标准化
# ─────────────────────────────────────────────────────────────────────────────
BODY_PART_NORMALIZATION: dict[str, dict] = {
    "头部": {
        "标准": "头部",
        "细分": ["前额", "额部", "颞部", "顶部", "枕部", "枕后", "面部", "头皮"],
    },
    "眼部": {
        "标准": "眼部",
        "细分": ["眼球", "眼睑", "结膜", "角膜", "瞳孔"],
    },
    "口部": {
        "标准": "口腔",
        "细分": ["口腔", "舌", "牙龈", "咽喉", "扁桃体"],
    },
    "颈部": {
        "标准": "颈部",
        "细分": ["前颈", "后颈", "颈侧", "甲状腺区"],
    },
    "胸部": {
        "标准": "胸部",
        "细分": ["胸骨区", "左胸", "右胸", "心前区", "肺部"],
    },
    "腹部": {
        "标准": "腹部",
        "细分": ["上腹部", "中腹部", "下腹部", "脐周", "左腹", "右腹"],
    },
    "背部": {
        "标准": "背部",
        "细分": ["上背部", "下背部", "腰背部", "脊柱旁"],
    },
    "上肢": {
        "标准": "上肢",
        "细分": ["肩部", "上臂", "肘部", "前臂", "腕部", "手部", "手指"],
    },
    "下肢": {
        "标准": "下肢",
        "细分": ["髋部", "大腿", "膝部", "小腿", "踝部", "足部", "脚趾"],
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# 急危重症关键词检测
# ─────────────────────────────────────────────────────────────────────────────
EMERGENCY_KEYWORDS: dict[str, float] = {
    # 癫痫持续状态
    "持续抽搐": 0.95,
    "一直抽": 0.95,
    "抽个不停": 0.95,
    "停不下来": 0.90,
    "5分钟以上": 0.95,
    "超过5分钟": 0.95,
    "status epilepticus": 0.98,
    # 意识障碍
    "叫不醒": 0.95,
    "不省人事": 0.90,
    "完全没有反应": 0.98,
    "呼吸不正常": 0.98,
    "嘴唇发紫": 0.95,
    "嘴唇发乌": 0.95,
    "喘不上气": 0.90,
    # 发作后状态
    "发作后一直不清醒": 0.90,
    "一直迷糊": 0.85,
    "Todd麻痹": 0.90,
    "发作后偏瘫": 0.95,
    # 外伤
    "咬舌头了": 0.85,
    "摔伤了": 0.80,
    "头部受伤": 0.90,
    "流血了": 0.75,
    # 妊娠相关
    "怀孕": 0.70,
    "妊娠": 0.70,
    "孕妇": 0.70,
    # 药物严重不良反应
    "皮疹": 0.60,
    "过敏": 0.60,
    "肝功能异常": 0.75,
    "血常规异常": 0.75,
}


# ─────────────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────────────


def get_dialect_dict() -> list[DialectEntry]:
    """获取完整的方言词典"""
    return SICHUAN_DIALECT_DICT


def get_colloquial_map() -> dict[str, str]:
    """获取口语症状映射"""
    return COLLOQUIAL_SYMPTOM_MAP


def get_symptom_expansion() -> dict[str, list[str]]:
    """获取症状同义词扩展"""
    return SYMPTOM_EXPANSION


def build_exact_match_index() -> dict[str, DialectEntry]:
    """构建方言词典精确匹配索引"""
    index: dict[str, DialectEntry] = {}
    for entry in SICHUAN_DIALECT_DICT:
        index[entry.source] = entry
    return index


def build_category_index() -> dict[str, list[DialectEntry]]:
    """按类别构建索引"""
    index: dict[str, list[DialectEntry]] = {}
    for entry in SICHUAN_DIALECT_DICT:
        if entry.category not in index:
            index[entry.category] = []
        index[entry.category].append(entry)
    return index

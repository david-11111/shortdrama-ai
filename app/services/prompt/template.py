import re

TEMPLATES = {
    "dialogue": {
        "label": "对话场景",
        "base": "A {style} cinematic scene of {subject} having a conversation, {atmosphere} atmosphere, {camera_angle} shot",
        "fields": {
            "style": "电影风格，如 realistic, dramatic, warm",
            "subject": "人物描述，如 two young women in a cafe",
            "atmosphere": "氛围，如 tense, romantic, casual",
            "camera_angle": "机位，如 medium close-up, over-the-shoulder",
        },
    },
    "action": {
        "label": "动作场景",
        "base": "A {style} action scene of {subject} {action}, {atmosphere} mood, {camera_angle} angle, fast paced",
        "fields": {
            "style": "电影风格，如 intense, gritty, stylized",
            "subject": "人物描述，如 a man in a black suit",
            "action": "动作描述，如 running through a rainy alley",
            "atmosphere": "氛围，如 thrilling, desperate, heroic",
            "camera_angle": "机位，如 tracking shot, low angle",
        },
    },
    "landscape": {
        "label": "风景空镜",
        "base": "A {style} landscape shot of {subject}, {atmosphere} lighting, {camera_angle} view, cinematic color grading",
        "fields": {
            "style": "画面风格，如 serene, epic, moody",
            "subject": "场景描述，如 a misty mountain at dawn",
            "atmosphere": "光线氛围，如 golden hour, overcast, neon-lit",
            "camera_angle": "机位，如 aerial, wide angle, panoramic",
        },
    },
    "transition": {
        "label": "转场过渡",
        "base": "A {style} transitional shot of {subject}, {atmosphere} tone, smooth {camera_angle} movement",
        "fields": {
            "style": "风格，如 dreamy, fast-cut, elegant",
            "subject": "画面内容，如 city lights blurring past",
            "atmosphere": "基调，如 melancholic, hopeful, neutral",
            "camera_angle": "运镜，如 dolly zoom, pan, tilt",
        },
    },
    "emotional": {
        "label": "情感特写",
        "base": "A {style} emotional close-up of {subject} {action}, {atmosphere} atmosphere, {camera_angle} framing",
        "fields": {
            "style": "风格，如 intimate, raw, soft-focus",
            "subject": "人物描述，如 a woman with tears in her eyes",
            "action": "表情/动作，如 looking out a window, smiling softly",
            "atmosphere": "氛围，如 bittersweet, heartwarming, lonely",
            "camera_angle": "构图，如 extreme close-up, shallow depth of field",
        },
    },
    "custom": {
        "label": "自定义",
        "base": "{subject} {action}, {style} style, {atmosphere}, {camera_angle}",
        "fields": {
            "style": "风格",
            "subject": "主体",
            "action": "动作",
            "atmosphere": "氛围",
            "camera_angle": "机位/构图",
        },
    },
    "gold_product": {
        "label": "黄金产品特写",
        "base": "Cinematic close-up of {subject} on {background}, {lighting} lighting, {camera_angle}, luxurious and elegant, 4K detail",
        "fields": {
            "subject": "产品，如 shiny gold bars, gold necklace, gold coins",
            "background": "背景，如 black velvet, marble surface, wooden desk",
            "lighting": "灯光，如 warm studio, dramatic side light, soft golden glow",
            "camera_angle": "机位，如 slow dolly in, rotating shot, macro lens",
        },
    },
    "gold_factory": {
        "label": "金厂/生产场景",
        "base": "A {style} shot of {subject}, {atmosphere}, industrial gold production, {camera_angle}",
        "fields": {
            "style": "风格，如 documentary, cinematic, dramatic",
            "subject": "场景，如 molten gold pouring into molds, gold bars cooling on conveyor belt, refinery furnace glowing",
            "atmosphere": "氛围，如 intense orange glow, steam and heat, professional and precise",
            "camera_angle": "机位，如 wide establishing shot, close-up detail, slow motion",
        },
    },
    "gold_trade": {
        "label": "黄金交易/商务",
        "base": "A {style} scene of {subject}, {atmosphere} mood, professional setting, {camera_angle}",
        "fields": {
            "style": "风格，如 corporate, elegant, modern",
            "subject": "场景，如 hands weighing gold on digital scale, signing documents next to gold bars, gold being packaged for shipping",
            "atmosphere": "氛围，如 trustworthy, serious, high-end",
            "camera_angle": "机位，如 over-the-shoulder, medium shot, detail insert",
        },
    },
    "gold_retail": {
        "label": "金店/零售场景",
        "base": "A {style} shot of {subject}, {atmosphere} lighting, luxury retail environment, {camera_angle}",
        "fields": {
            "style": "风格，如 warm, glamorous, inviting",
            "subject": "场景，如 jewelry display case with gold necklaces, customer examining gold bracelet, shop counter with gold products",
            "atmosphere": "灯光，如 warm spotlights, soft ambient glow, bright showcase lighting",
            "camera_angle": "机位，如 slow pan across display, close-up on hands, wide shot of store",
        },
    },
    "gold_price": {
        "label": "金价/数据画面",
        "base": "A {style} shot of {subject}, {atmosphere}, financial and analytical feel, {camera_angle}",
        "fields": {
            "style": "风格，如 modern, tech, clean",
            "subject": "画面，如 gold price chart on screen trending upward, financial data dashboard with gold ticker, newspaper headline about gold prices",
            "atmosphere": "氛围，如 blue-tinted monitor glow, urgent newsroom feel, calm analytical mood",
            "camera_angle": "机位，如 slow zoom into screen, rack focus, static wide",
        },
    },
    "gold_host": {
        "label": "黄金博主出镜（远景/背影/手部）",
        "base": "A {style} shot of a Chinese woman in her mid-30s with medium-length auburn brown hair, wearing {outfit}, {action}, in a luxury jewelry showroom with crystal chandeliers and glass display cases, {camera_angle}, no face visible",
        "fields": {
            "style": "风格，如 elegant, professional, warm",
            "outfit": "服装，如 black damask-patterned blouse, white silk blouse, dark blazer",
            "action": "动作，如 examining a gold bar on the counter, arranging gold jewelry in display case, writing notes beside a digital scale",
            "camera_angle": "机位，如 over-the-shoulder, hands close-up, silhouette from behind, wide shot from back",
        },
    },
}


PRESETS = {
    "gold_bangle_charms": {
        "label": "古法转运珠手镯",
        "prompt": "Cinematic close-up of a woman's hand holding an intricate 24K gold bangle with multiple small dangling charms including coins and lucky symbols, ancient Chinese gold craftsmanship with textured matte finish, on a dark leather surface, warm studio lighting, slow rotating shot, 4K detail",
    },
    "gold_auspicious_pendant": {
        "label": "八吉祥宝石金吊坠",
        "prompt": "Extreme close-up of fingers holding a round 24K gold pendant with intricate Tibetan eight auspicious symbols in relief, surrounded by a circle of small diamonds with a green emerald at the center, on a braided gold chain, dark red gift box in background, dramatic side lighting, macro lens",
    },
    "gold_buddha_pendants": {
        "label": "古法弥勒佛吊坠",
        "prompt": "A hand displaying four matte satin-finish 24K gold laughing Buddha pendants in graduated sizes, ancient Chinese gold craftsmanship, smooth rounded surface with fine border engravings, dark leather surface, dark gift box with gold lattice pattern behind, soft warm lighting, slow dolly in",
    },
    "gold_deer_figurine": {
        "label": "古法金鹿摆件",
        "prompt": "A detailed 24K gold deer figurine with elegant antlers, matte satin finish, standing gracefully next to a dark wooden gift box with gold lattice pattern, ancient Chinese gold craftsmanship, dark background, studio product lighting with warm highlights, slow rotating shot, 4K",
    },
    "gold_bars_stack": {
        "label": "金条堆叠特写",
        "prompt": "Cinematic close-up of neatly stacked 24K gold investment bars with serial numbers engraved, on a dark velvet surface, warm golden studio lighting reflecting off polished surfaces, slow dolly movement, luxurious and weighty feel, 4K",
    },
    "gold_melting": {
        "label": "黄金熔炼",
        "prompt": "Dramatic slow motion shot of molten gold being poured from a crucible into a bar mold, intense orange glow illuminating the scene, sparks and steam rising, industrial gold refinery setting, cinematic color grading, 4K",
    },
    "gold_weighing": {
        "label": "黄金称重",
        "prompt": "Close-up of hands placing a gold bar onto a precision digital scale, numbers displaying on the screen, dark professional desk surface, soft overhead lighting, steady medium close-up shot, professional and trustworthy atmosphere",
    },
    "gold_shop_display": {
        "label": "金店柜台展示",
        "prompt": "Slow cinematic pan across a luxury gold jewelry display case, warm spotlights illuminating gold necklaces, bracelets and rings on velvet stands, crystal chandelier reflections, green velvet curtains in background, elegant and inviting atmosphere, 4K",
    },
}


def list_templates() -> list[dict]:
    templates = [
        {
            "type": key,
            "label": tpl["label"],
            "fields": tpl["fields"],
        }
        for key, tpl in TEMPLATES.items()
    ]
    presets = [
        {
            "preset": key,
            "label": p["label"],
            "prompt": p["prompt"],
        }
        for key, p in PRESETS.items()
    ]
    return {"templates": templates, "presets": presets}


def get_preset_prompt(preset_name: str) -> str:
    p = PRESETS.get(preset_name)
    if not p:
        raise ValueError(f"unknown preset: {preset_name}")
    return p["prompt"]


def build_prompt(template_type: str, fields: dict[str, str]) -> str:
    tpl = TEMPLATES.get(template_type)
    if not tpl:
        raise ValueError(f"unknown template type: {template_type}")

    result = tpl["base"]
    for key in tpl["fields"]:
        value = fields.get(key, "").strip()
        result = result.replace(f"{{{key}}}", value)

    result = re.sub(r"\{[a-z_]+\}", "", result)
    result = re.sub(r"[, ]{2,}", ", ", result)
    result = re.sub(r"(^[, ]+|[, ]+$)", "", result)
    return result.strip()

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

from app.services.story_understanding import build_story_understanding


def build_planning_result_v2(
    project_id: str,
    brain: dict[str, Any],
    *,
    instruction: str,
    name: str,
    story_understanding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project_name = (name or project_id).strip() or project_id
    user_intent = instruction.strip() or _infer_intent(brain, project_name)
    scale = _infer_production_scale(user_intent)
    story_understanding = story_understanding or build_story_understanding(user_intent)
    intent = _extract_story_intent_constraints(user_intent, project_name, story_understanding=story_understanding)
    now = datetime.now(timezone.utc).isoformat()

    continuity = {
        "character_continuity": intent["character_lock"],
        "scene_continuity": intent["scene_lock"],
        "prop_continuity": intent["prop_lock"],
    }
    execution_plan = {
        "character_master": continuity["character_continuity"],
        "scene_master": continuity["scene_continuity"],
        "camera_plan": intent["camera_plan"],
        "performance_beats": intent["performance_plan"],
    }
    shot_rows = _build_initial_batch_shots(project_name, scale, continuity, execution_plan, intent)
    reply = (
        f"## 项目启动规划 {now}\n\n"
        f"### 用户核心诉求\n{intent['summary']}\n\n"
        f"### 剧本理解\n{user_intent}\n\n"
        "### 生产规模\n"
        f"- 目标时长：约 {scale['target_duration_seconds']} 秒\n"
        f"- 预计总镜头：约 {scale['estimated_total_shots']} 个\n"
        f"- 当前落盘批次：第 1 批，{scale['initial_batch_shots']} 个分镜\n\n"
        "### 第一场目标\n"
        f"{intent['scene_goal']}\n\n"
        "### 生产原则\n"
        "先锁定主角身份、场景、表演风格和镜头语法，再生成关键帧；每个分镜必须继承用户核心诉求，不能退化成泛化短剧模板。"
    )
    return {
        "reply": reply,
        "continuity": continuity,
        "execution_plan": execution_plan,
        "intent_constraints": intent,
        "story_understanding": story_understanding,
        "production_scale": scale,
        "shot_rows": shot_rows,
        "recommended_locks": ["character", "scene", "prop", "style"],
        "recommended_keyframe_beats": [
            {"shot_index": row["shot_index"], "beat": _beat_for_index(int(row["shot_index"]))}
            for row in shot_rows
        ],
        "quality_gate": {
            "allow_storyboard": True,
            "allow_reference_images": True,
            "allow_video_production": False,
            "reason": "已生成启动规划，但必须先确认主角、场景和表演锚点，再进入关键帧/视频生产。",
        },
    }


def _extract_story_intent_constraints(
    instruction: str,
    project_name: str,
    *,
    story_understanding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = str(instruction or "").strip()
    story_understanding = story_understanding or build_story_understanding(text)
    entity = story_understanding.get("entity_resolution") if isinstance(story_understanding.get("entity_resolution"), dict) else {}
    requirement_card = story_understanding.get("understanding_card") if isinstance(story_understanding.get("understanding_card"), dict) else {}
    if str(story_understanding.get("demand_type") or requirement_card.get("demand_type") or "").strip() == "product_ad":
        return _product_ad_intent_constraints(text, project_name, story_understanding)
    if _is_courier_office_delivery_intent(text):
        return {
            "story_type": "courier_office_delivery",
            "summary": "一名快递员把重要包裹送进高档写字楼的黄金区，核心看点是身份落差、门禁压力、包裹交接和楼宇空间质感。",
            "lead_reference": "快递员",
            "story_understanding": story_understanding,
            "character_lock": f"{project_name} 的主角锁定为一名现实感快递员：蓝灰色或深色配送工装、斜挎包、手持包裹或签收单，疲惫但专注，不能退化成泛化电视剧主角。",
            "scene_lock": "场景锁定在高档写字楼黄金区：玻璃幕墙大堂、安保台、前台、门禁闸机、电梯厅、金色导视牌和干净商务灯光，不能变成普通街道、金店或无身份空景。",
            "prop_lock": "关键道具是快递包裹、手持扫码枪或手机、签收单、门禁卡/访客贴、写字楼黄金区导视牌；每个镜头至少保留快递包裹或楼宇身份线索之一。",
            "camera_plan": "先用高档写字楼空间建立身份落差，再用快递员近景、门禁交涉、包裹特写和电梯厅推进，画面最多两名核心人物同框。",
            "performance_plan": "表演克制现实：快递员看楼层信息、递包裹、等待核验、被安保拦停、重新确认地址，情绪从赶时间到紧张再到完成交付。",
            "scene_goal": "第一场必须让观众看懂：快递员要把包裹送到高档写字楼黄金区，但门禁和身份差异让交付变成一个有压力的短剧事件。",
            "reference_plan": "参考图优先生成快递员工装、写字楼大堂/电梯厅、包裹签收道具、金色导视牌和商务冷暖混合灯光。",
            "must_not": "不要金店回收、不要人群排队、不要把快递员变成西装白领、不要丢掉包裹交付目标。",
        }
    if _is_real_project_process_intent(text):
        return {
            "story_type": "real_project_process",
            "summary": "\u56f4\u7ed5\u4e00\u4e2a\u666e\u901a\u4eba\u575a\u6301\u5f00\u53d1\u7cbe\u54c1\u77ed\u5267 Agent \u5de5\u5177\u7684\u771f\u5b9e\u8fc7\u7a0b\uff1a\u4ece\u4fe1\u5fc3\u3001\u5d29\u6e83\u3001\u6000\u7591\u5230\u91cd\u65b0\u628a\u94fe\u8def\u8dd1\u901a\u3002",
            "lead_reference": "\u77ed\u5267\u5de5\u5177\u5f00\u53d1\u8005",
            "story_understanding": story_understanding,
            "character_lock": "\u4e3b\u89d2\u662f\u4e00\u4f4d\u6df1\u591c\u5de5\u4f5c\u7684\u77ed\u5267\u5de5\u5177\u5f00\u53d1\u8005\uff0c\u73b0\u5b9e\u3001\u514b\u5236\u3001\u75b2\u60eb\u4f46\u4ecd\u6709\u6267\u5ff5\uff0c\u4e0d\u80fd\u9000\u5316\u6210\u6cdb\u5316\u7535\u89c6\u5267\u4e3b\u89d2\u3002",
            "scene_lock": "\u573a\u666f\u9501\u5b9a\u5728\u6df1\u591c\u5de5\u4f5c\u684c\u3001\u7535\u8111\u5c4f\u5e55\u3001\u6587\u6863\u3001\u6d4b\u8bd5\u7ec8\u7aef\u3001\u751f\u6210\u5931\u8d25\u7684\u53c2\u8003\u56fe\u548c\u89c6\u9891\u9884\u89c8\u4e4b\u95f4\u3002",
            "prop_lock": "\u5173\u952e\u9053\u5177\u662f\u6d4b\u8bd5\u65e5\u5fd7\u3001\u94fe\u8def\u8282\u70b9\u754c\u9762\u3001\u5931\u8d25\u63d0\u793a\u3001\u9700\u6c42\u6587\u6863\u3001\u53c2\u8003\u56fe\u5360\u4f4d\u548c\u89c6\u9891\u9884\u89c8\u6846\u3002",
            "camera_plan": "\u5148\u7528\u7535\u8111\u5c4f\u5e55\u548c\u6d4b\u8bd5\u65e5\u5fd7\u5efa\u7acb\u771f\u5b9e\u56f0\u5883\uff0c\u518d\u7ed9\u5f00\u53d1\u8005\u8fd1\u666f\u53cd\u5e94\uff0c\u6700\u540e\u843d\u5230\u94fe\u8def\u91cd\u65b0\u8dd1\u901a\u7684\u5c0f\u5c4f\u5e55\u8bc1\u636e\u3002",
            "performance_plan": "\u8868\u6f14\u514b\u5236\uff1a\u76ef\u5c4f\u3001\u505c\u987f\u3001\u6df1\u547c\u5438\u3001\u91cd\u65b0\u70b9\u51fb\u8fd0\u884c\uff0c\u60c5\u7eea\u4ece\u5d29\u6e83\u538b\u6291\u8f6c\u5411\u91cd\u65b0\u5224\u65ad\u95ee\u9898\u3002",
            "scene_goal": "\u7b2c\u4e00\u573a\u5fc5\u987b\u8ba9\u89c2\u4f17\u7acb\u523b\u770b\u61c2\uff1a\u8fd9\u662f\u4e00\u4e2a\u4eba\u5728\u505a\u77ed\u5267 Agent \u5de5\u5177\u65f6\u9047\u5230\u94fe\u8def\u5931\u63a7\u7684\u771f\u5b9e\u538b\u529b\u3002",
        }
    actor_match = re.search(r"([\u4e00-\u9fff]{2,4})\s*(?:演|饰演|主演)", text)
    actor = actor_match.group(1) if actor_match else ""
    if "张嘉益" in text:
        actor = "张嘉益"
    drama_hint = "电视剧主角" if "电视剧" in text or "剧" in text else "主角"
    duration_hint = "前一分钟" if "前一分钟" in text or "最初1分钟" in text or "最初一分钟" in text else "开场段落"
    if entity:
        work_title = entity["work_title"]
        role_name = entity["role_name"]
        role_identity = entity["role_identity"]
        lead_reference = f"{entity['actor']}饰演的{role_name}（电视剧《{work_title}》{role_identity}）"
        scene_text = "、".join(entity["scene_anchors"])
        prop_text = "、".join(entity["prop_anchors"])
        action_text = "、".join(entity["action_anchors"])
        tone_text = "、".join(entity["tone_anchors"])
        must_not = "、".join(entity["must_not"])
        summary = (
            f"围绕电视剧《{work_title}》里{lead_reference}的{duration_hint}戏："
            f"先进入{entity['story_world']}，让观众识别{role_name}是秦腔剧团人，而不是泛化电视剧男主。"
        )
        return {
            "summary": summary,
            "lead_reference": lead_reference,
            "entity_resolution": entity,
            "story_understanding": story_understanding,
            "character_lock": (
                f"{project_name} 必须锁定为{lead_reference}；人物气质是西北剧团里的秦腔司鼓，"
                "中年、沉稳、会看戏也会压场，脸部清楚可辨；不得复制真人脸，只参考戏路和角色气质。"
            ),
            "scene_lock": f"{duration_hint}必须发生在《{work_title}》的秦腔剧团语境内，优先场景：{scene_text}；禁止脱离到现代办公室、派出所或无身份空场。",
            "prop_lock": f"关键道具必须服务秦腔剧团身份：{prop_text}；不允许用无关道具替代{role_name}的司鼓/剧团人身份。",
            "camera_plan": f"镜头语言围绕{role_name}和秦腔空间：先给剧团后台/戏台边环境，再给{role_name}半身与手上鼓槌，关系镜头要能看清他和排练/戏台的关系。",
            "performance_plan": f"表演节奏围绕{role_name}：少说、多看，动作重点是{action_text}；情绪从审视、压场到把人带进戏门。",
            "scene_goal": f"第一场必须让观众知道这是电视剧《{work_title}》的秦腔世界，{role_name}是{role_identity}，这一分钟要建立他和剧团/舞台/后辈的关系。",
            "reference_plan": f"参考图优先生成：{role_name}角色参考、县剧团后台/排练场场景参考、{prop_text}道具参考、{tone_text}风格参考。",
            "must_not": must_not,
        }
    lead_reference = f"{actor}演的{drama_hint}" if actor else drama_hint
    lead_visual = (
        f"{lead_reference}：中年现实主义男主气质，沉稳、克制、生活感强，脸部必须清楚可辨；"
        "不得退化成无身份路人或空镜。"
    )
    if actor:
        lead_visual += " 使用演员名作为戏路和角色气质参考，不要求复制真人脸。"
    summary = f"围绕{lead_reference}的{duration_hint}戏，先理解人物身份、处境、动作目标和情绪推进，再拆成可拍分镜。"
    return {
        "summary": summary,
        "lead_reference": lead_reference,
        "story_understanding": story_understanding,
        "character_lock": f"{project_name} 必须锁定为{lead_visual}",
        "scene_lock": f"{duration_hint}必须服务{lead_reference}出场：先交代处境和空间，再推进人物动作、对手关系和情绪反应。",
        "prop_lock": "关键道具只在能推动人物处境或冲突时出现，不允许用无关道具替代主角戏。",
        "camera_plan": f"镜头语言围绕{lead_reference}：建立镜头要有主角正面或半身，关系镜头要能看清主角位置，反应镜头要给主角表情。",
        "performance_plan": f"表演节奏围绕{lead_reference}：少说、多看、动作克制，重点拍眼神、停顿、转身、递交、对视等现实主义表演节拍。",
        "scene_goal": f"第一场必须让观众知道{lead_reference}是谁、他现在面对什么处境、这一分钟内情绪如何变化。",
    }


def _is_real_project_process_intent(text: str) -> bool:
    value = str(text or "")
    if "AI" not in value and "agent" not in value.lower():
        return False
    process_terms = (
        "\u5de5\u5177",
        "\u9879\u76ee",
        "\u94fe\u8def",
        "\u6d4b\u8bd5",
        "\u77ed\u5267",
        "\u4e00\u4e2a\u6708",
        "\u5d29\u6e83",
        "\u8dd1\u901a",
        "工具",
        "项目",
        "链路",
        "测试",
        "短剧",
        "崩溃",
        "跑通",
    )
    return any(term in value for term in process_terms)


def _is_courier_office_delivery_intent(text: str) -> bool:
    value = str(text or "")
    has_courier = any(term in value for term in ("快递员", "快递", "配送员", "送件"))
    has_office = any(term in value for term in ("写字楼", "办公楼", "大厦", "电梯厅", "前台", "门禁"))
    has_delivery = any(term in value for term in ("送", "包裹", "签收", "投递", "交付"))
    return has_courier and has_office and has_delivery


def _product_ad_intent_constraints(
    instruction: str,
    project_name: str,
    story_understanding: dict[str, Any],
) -> dict[str, Any]:
    card = story_understanding.get("understanding_card") if isinstance(story_understanding.get("understanding_card"), dict) else {}
    subject = str(card.get("subject") or project_name or "产品广告").strip()
    props = _join_card_items(card.get("prop_anchors")) or subject
    visuals = _join_card_items(card.get("visual_anchors")) or "产品特写、使用效果展示"
    actions = _join_card_items(card.get("action_anchors")) or "展示产品、使用产品、呈现效果"
    tones = _join_card_items(card.get("tone_anchors")) or "商业广告质感、干净高级"
    selling_points = _join_card_items(card.get("selling_points")) or "产品质感、可见效果"
    must_not = _join_card_items(card.get("must_not")) or "不要短剧冲突、不要让人物抢产品重心"
    library_context = story_understanding.get("library_context") if isinstance(story_understanding.get("library_context"), dict) else {}
    matched_names = [str(item).strip() for item in library_context.get("matched_names", []) if str(item).strip()]
    library_summary = "、".join(matched_names[:6])
    summary = (
        f"{subject}，类型为产品广告；核心卖点是{selling_points}；"
        f"画面必须围绕{props}、{visuals}和{actions}展开，整体保持{tones}。"
    )
    return {
        "story_type": "product_ad",
        "summary": summary,
        "lead_reference": subject,
        "story_understanding": story_understanding,
        "library_context_summary": library_summary,
        "character_lock": f"人物只作为产品使用和效果展示的辅助，不抢{subject}的画面重心；如出现手部或眼部，必须服务{props}。",
        "scene_lock": f"场景锁定为商业广告拍摄空间：极简干净背景、柔和可控布光、产品和使用部位清晰可见；视觉锚点：{visuals}。",
        "prop_lock": f"产品和道具锁定：{props}；每个镜头都要保持产品外观、位置、材质和效果连续。",
        "camera_plan": f"镜头语言按广告片处理：开场钩子、产品微距、使用动作、效果展示、品牌质感收尾；优先使用{visuals}。",
        "performance_plan": f"动作只服务产品：{actions}；节奏克制、干净、可见，不做戏剧冲突。",
        "scene_goal": f"第一批分镜必须让观众立刻看懂这是{subject}，并看到产品、使用动作和效果；风格保持{tones}。",
        "reference_plan": f"参考图优先生成产品/道具、使用部位、商业棚拍光影和最终效果；词库命中：{library_summary or '无'}。",
        "must_not": must_not,
    }


def _join_card_items(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple, set)):
        return "、".join(str(item).strip() for item in value if str(item).strip())
    return ""


def _build_initial_batch_shots(
    project_name: str,
    scale: dict[str, Any],
    continuity: dict[str, str],
    execution_plan: dict[str, str],
    intent: dict[str, str],
) -> list[dict[str, Any]]:
    shot_count = int(scale.get("initial_batch_shots") or 3)
    anchor = intent["lead_reference"]
    if intent.get("story_type") == "product_ad":
        story_understanding = intent.get("story_understanding") if isinstance(intent.get("story_understanding"), dict) else {}
        card = story_understanding.get("understanding_card") if isinstance(story_understanding.get("understanding_card"), dict) else {}
        subject = str(card.get("subject") or anchor or project_name).strip()
        props = _join_card_items(card.get("prop_anchors")) or subject
        visuals = _join_card_items(card.get("visual_anchors")) or "产品特写、使用效果展示"
        actions = _join_card_items(card.get("action_anchors")) or "展示产品、使用产品、呈现效果"
        tones = _join_card_items(card.get("tone_anchors")) or "商业广告质感、干净高级"
        selling_points = _join_card_items(card.get("selling_points")) or "产品质感、可见效果"
        library = str(intent.get("library_context_summary") or "").strip()
        library_note = f"词库命中：{library}；" if library else ""
        templates = [
            ("广告钩子", f"{library_note}{subject}开场，画面先给{visuals}，用干净柔和光线建立{tones}，前三秒明确这是产品广告而不是剧情片。", 3),
            ("产品特写", f"{subject}的产品和道具清晰占据画面中心：{props}；镜头用微距、慢推或稳定环绕展示{selling_points}，背景极简不抢重心。", 3),
            ("使用动作", f"展示真实可见的使用动作：{actions}；动作节奏克制、手部或眼部稳定清楚，产品始终是画面焦点。", 4),
            ("效果展示", f"切到效果呈现：{visuals}；让观众看到使用后的具体变化，保持{tones}，不加入冲突人物关系。", 4),
            ("质感收尾", f"{subject}以商业广告方式收尾，产品、效果和品牌调性同时成立；字幕或标语极简，画面继续保持{tones}。", 4),
            ("细节补强", f"补一个{props}的细节镜头，强调材质、轮廓、高光和可见效果；镜头稳定、构图留白、质感高级。", 3),
            ("场景统一", f"回到统一广告拍摄空间，背景、光线、产品位置和使用部位保持连续；避免杂物、路人和剧情化表演。", 3),
            ("品牌落点", f"最后用{subject}的产品视觉完成落点，画面简洁，保留{selling_points}和{tones}，可衔接品牌 LOGO 或短句。", 4),
        ]
    elif intent.get("story_type") == "courier_office_delivery":
        templates = [
            ("写字楼建立", f"{anchor}站在高档写字楼黄金区玻璃大堂入口，手里拿着包裹和手机地址页，金色导视牌、门禁闸机和前台清楚可见，建立送达目标和空间质感。", 4),
            ("快递员身份", f"{anchor}半身近景，配送工装、斜挎包、包裹标签和微微出汗的脸部状态清楚，体现赶时间但克制的现实感。", 4),
            ("门禁受阻", f"{anchor}在安保台前递出手机订单和包裹，安保或前台只出现一人同框核验，画面重点是快递员被门禁流程拦住。", 5),
            ("包裹特写", f"快递包裹、签收单、手机楼层信息和黄金区导视牌同框特写，手部动作清楚，说明他要送到高档写字楼内部指定楼层。", 3),
            ("电梯厅推进", f"{anchor}穿过闸机后站在电梯厅看楼层屏，玻璃墙、金属电梯门和商务灯光保持统一，动作目标是继续完成交付。", 4),
            ("压力反应", f"{anchor}听到前台再次确认收件人信息后停顿，近景强调眼神和手里的包裹，不允许变成空镜或路人群像。", 4),
            ("交接瞬间", f"{anchor}把包裹递给写字楼工作人员或收件人，双方最多两人同框，签收动作明确，包裹始终是画面核心道具。", 5),
            ("完成落点", f"{anchor}走出电梯厅或大堂回头看一眼黄金区导视牌，手机显示已签收，留下高档写字楼与普通快递员身份落差的余味。", 4),
        ]
    elif intent.get("entity_resolution"):
        templates = [
            ("剧团环境", f"县剧团后台或排练场里，{anchor}站在锣鼓家伙旁，半身正面可辨，先交代秦腔班社空间和他的司鼓身份。", 5),
            ("司鼓身份", f"{anchor}低头检查鼓槌和旧谱本，手部动作清楚，衣着有西北县剧团年代生活感。", 4),
            ("排练关系", f"{anchor}看着戏台边排练的人，眼神审视，和排练场/后辈形成明确关系，画面不超过两名核心人物。", 5),
            ("秦腔反应", f"{anchor}听到唱腔或锣鼓点不稳后停顿抬眼，脸部和眼神给出压场反应，观众能读懂他懂戏。", 4),
            ("动作推进", f"{anchor}拿起鼓槌敲出一个清楚鼓点，或把旧谱本递给后辈，动作推动她进入秦腔世界。", 5),
            ("师承压力", f"{anchor}在戏台边压低声音训戏，近景强调脸部和手上鼓槌，不允许变成空镜或无身份路人。", 5),
            ("后辈对位", f"后辈被点醒后切回{anchor}，他仍站在锣鼓点旁，形成师承/托举关系，而不是普通冲突反打。", 4),
            ("一分钟落点", f"{anchor}在后台灯光里停住，看向戏台或把鼓槌放回鼓边，以秦腔舞台气息结束这一分钟。", 4),
        ]
    elif intent.get("story_type") == "real_project_process":
        templates = [
            ("\u5931\u8d25\u65e5\u5fd7\u5efa\u7acb", "\u6df1\u591c\u5de5\u4f5c\u684c\u524d\uff0c\u77ed\u5267\u5de5\u5177\u5f00\u53d1\u8005\u76ef\u7740\u7b2c\u56db\u6b21\u5931\u8d25\u7684\u6d4b\u8bd5\u65e5\u5fd7\uff0c\u7535\u8111\u5c4f\u5e55\u51b7\u5149\u538b\u5728\u8138\u4e0a\uff0c\u804c\u8d23\u662f\u5efa\u7acb\u771f\u5b9e\u56f0\u5883\u548c\u524d\u4e09\u79d2\u94a9\u5b50\u3002", 3),
            ("\u94fe\u8def\u5361\u70b9", "\u7535\u8111\u5c4f\u5e55\u4e0a\u540c\u65f6\u663e\u793a storyboard\u3001image_gen\u3001video_gen \u4e09\u4e2a\u94fe\u8def\u8282\u70b9\uff0cimage_gen \u4e3a 0\uff0c\u5f00\u53d1\u8005\u624b\u6307\u505c\u5728\u9f20\u6807\u4e0a\u6ca1\u6709\u70b9\u4e0b\u53bb\uff0c\u804c\u8d23\u662f\u8ba9\u89c2\u4f17\u770b\u89c1\u95ee\u9898\u3002", 3),
            ("\u91cd\u65b0\u5224\u65ad", "\u5f00\u53d1\u8005\u628a\u4e00\u5f20\u5931\u8d25\u53c2\u8003\u56fe\u548c\u9700\u6c42\u6587\u6863\u5e76\u6392\u653e\u5728\u5c4f\u5e55\u4e0a\uff0c\u773c\u795e\u4ece\u7126\u8e81\u53d8\u6210\u51b7\u9759\uff0c\u753b\u9762\u4e0d\u8d85\u8fc7\u4e00\u4e2a\u4eba\uff0c\u804c\u8d23\u662f\u8868\u8fbe\u6839\u56e0\u5b9a\u4f4d\u3002", 2),
            ("\u8dd1\u901a\u843d\u70b9", "\u7ec8\u7aef\u754c\u9762\u51fa\u73b0\u65b0\u7684 dispatch_gateway \u548c decision_mailbox \u8bb0\u5f55\uff0c\u5f00\u53d1\u8005\u6ca1\u6709\u6b22\u547c\uff0c\u53ea\u662f\u8f7b\u8f7b\u677e\u5f00\u624b\uff0c\u804c\u8d23\u662f\u7ed9\u51fa\u514b\u5236\u4f46\u6709\u529b\u7684\u7ed3\u5c3e\u3002", 2),
        ]
    else:
        templates = [
            ("建立镜头", f"{anchor}进入核心场景，正面或半身可辨，交代他所处环境和人物压力。", 5),
            ("身份细节", f"{anchor}的衣着、步态、手部动作和脸部状态清楚，体现现实主义电视剧质感。", 4),
            ("关系镜头", f"{anchor}与对手方形成明确关系，画面不超过两名核心人物，主角位置不能被遮挡。", 5),
            ("反应镜头", f"{anchor}听到关键信息后停顿，眼神变化清楚，情绪克制但观众能读懂。", 4),
            ("动作推进", f"{anchor}完成一个推动剧情的动作，如递交、推门、转身、坐下或抬眼对视。", 5),
            ("情绪压迫", f"{anchor}被逼到选择节点，近景强调脸部和眼神，不允许变成空镜或路人群像。", 5),
            ("对手反打", f"对手方施压后切回{anchor}，形成可剪辑对位，主角仍是戏剧重心。", 4),
            ("落点镜头", f"{anchor}以一个背影、停顿或眼神落点结束这一分钟，留下下一场承接。", 4),
        ]
    rows: list[dict[str, Any]] = []
    for index in range(1, shot_count + 1):
        label, prompt, duration = templates[(index - 1) % len(templates)]
        scene_no = int(math.ceil(index / 8))
        rows.append({
            "shot_index": index,
            "prompt": f"第1集第{scene_no}场，{label}：{project_name}，{intent['summary']}。{prompt}",
            "duration": duration,
            "status": "pending",
            "continuity": continuity,
            "execution_plan": execution_plan,
            "production_batch": {
                "batch_index": 1,
                "target_total_shots": scale.get("estimated_total_shots"),
                "target_scene_count": scale.get("estimated_scene_count"),
            },
        })
    return rows


def _infer_production_scale(instruction: str) -> dict[str, Any]:
    duration_seconds = _extract_duration_seconds(instruction) or 60
    is_long_form = duration_seconds >= 10 * 60
    avg_shot_seconds = 5 if is_long_form else 4
    estimated_total_shots = max(1, int(math.ceil(duration_seconds / avg_shot_seconds)))
    estimated_scene_count = max(1, int(math.ceil(duration_seconds / (60 if is_long_form else 30))))
    if is_long_form:
        initial_batch_shots = min(24, max(12, int(math.ceil(estimated_total_shots * 0.04))))
    else:
        initial_batch_shots = min(8, max(3, estimated_total_shots))
    return {
        "target_duration_seconds": duration_seconds,
        "estimated_total_shots": estimated_total_shots,
        "estimated_scene_count": estimated_scene_count,
        "avg_shot_seconds": avg_shot_seconds,
        "initial_batch_shots": initial_batch_shots,
        "batching_policy": "scene_batch" if is_long_form else "single_scene",
    }


def _extract_duration_seconds(text: str) -> int | None:
    compact = str(text or "")
    patterns = [
        (r"(\d+(?:\.\d+)?)\s*(?:分钟|min|mins|minute|minutes)", 60),
        (r"(\d+(?:\.\d+)?)\s*(?:小时|h|hour|hours)", 3600),
        (r"(\d+(?:\.\d+)?)\s*(?:秒|s|sec|secs|second|seconds)", 1),
    ]
    for pattern, multiplier in patterns:
        match = re.search(pattern, compact, flags=re.IGNORECASE)
        if match:
            return max(1, int(float(match.group(1)) * multiplier))
    return None


def _beat_for_index(index: int) -> str:
    beats = [
        "建立空间与主角身份",
        "推进人物关系和冲突",
        "捕捉主角反应",
        "锁定道具或证据",
        "推进动作",
        "强化情绪压力",
        "形成反打关系",
        "给出转场落点",
    ]
    return beats[(index - 1) % len(beats)]


def _infer_intent(brain: dict[str, Any], project_name: str) -> str:
    context = brain.get("context") if isinstance(brain.get("context"), dict) else {}
    project_context = str(context.get("project") or "").strip()
    if project_context:
        return f"围绕《{project_name}》制作精品短剧，先落定剧本理解、人物关系和第一场生产路径。"
    return f"围绕《{project_name}》建立精品短剧项目的第一场规划。"

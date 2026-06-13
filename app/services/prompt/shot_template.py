"""Structured shot templates for Seedance prompt assembly.

Each ShotTemplate describes one 15-second Seedance clip at the sub-shot level:
shot_type / duration / product_reveal / sfx_hint / end_beat.

Templates are keyed by scene_type (e.g. "烈日", "暴雨", "深夜", "结尾闭环")
and can be retrieved via get_templates_for_scene().
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class SubShot:
    index: int
    duration: float
    shot_type: str        # 景别+运镜，e.g. "全景·手持跟拍"
    angle: str            # 拍摄角度，e.g. "侧前方45度"
    distance: str         # 拍摄距离，e.g. "远距离" / "近距离"
    description: str      # 画面描述（纯视觉，无台词音效）
    product_reveal: str   # 产品露出方式，e.g. "自然带入" / "特写定格" / "环境融合" / "无"
    sfx_hint: str         # 音效提示（给剪辑参考，不进Seedance提示词）

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ShotTemplate:
    scene_type: str                          # 场景标签，e.g. "暴雨"
    clip_index: int                          # 片段序号（同场景可有多个片段）
    duration: float                          # 总时长（秒）
    style_lock: str                          # 固定风格串，直接拼入提示词
    color_temp: str                          # 色温锚定，e.g. "6000K"
    color_grade: str                         # 影调描述，e.g. "冷灰蓝调为主"
    end_beat: str                            # 结尾节拍，e.g. "慢镜留白1秒" / "硬切" / "慢溶"
    character_lock: str                      # 人物一致性约束
    sub_shots: list[SubShot] = field(default_factory=list)
    constraint: str = "画面稳定，动作连续不跳帧，色调统一不跳变"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    def to_seedance_prompt(self) -> str:
        """Render this template into a Seedance-ready prompt string."""
        lines: list[str] = []

        # 场景画面：逐分镜拼接
        shot_descs = [
            f"分镜{s.index}（{s.duration}s，{s.shot_type}，{s.angle}）：{s.description}"
            for s in self.sub_shots
        ]
        lines.append("场景画面：" + "；".join(shot_descs))

        lines.append(f"整体风格：{self.style_lock}")
        lines.append(
            f"镜头语言：{'→'.join(s.shot_type for s in self.sub_shots)}，运镜稳定，节奏连贯"
        )
        lines.append(f"光影要求：色温{self.color_temp}，{self.color_grade}")
        lines.append(f"色调要求：{self.color_grade}，哑光质感")
        lines.append(f"{self.character_lock}")
        lines.append(f"画面约束：{self.constraint}，结尾{self.end_beat}")

        # 产品露出汇总
        reveals = [s.product_reveal for s in self.sub_shots if s.product_reveal != "无"]
        if reveals:
            lines.append(f"产品露出：{'；'.join(reveals)}")

        return "。".join(lines) + "。"


# ---------------------------------------------------------------------------
# 内置模板库
# ---------------------------------------------------------------------------

SHOT_TEMPLATE_LIBRARY: list[ShotTemplate] = [

    # ── 第一段：开篇 + 烈日 ──────────────────────────────────────────────
    ShotTemplate(
        scene_type="烈日",
        clip_index=1,
        duration=15.0,
        style_lock="低饱和写实质感，电影宽幅，哑光色调",
        color_temp="6500K",
        color_grade="高亮暖白调，轻微过曝，热浪感",
        end_beat="慢镜留白1秒，热浪微微扭曲画面边缘",
        character_lock="人物面容、发型、气质全程保持一致，无变脸；穿着工装，贴合户外骑行场景",
        constraint="人物动作连续不跳帧，屏幕显示稳定，光影统一不跳变",
        sub_shots=[
            SubShot(
                index=1, duration=4.0,
                shot_type="特写·固定",
                angle="俯拍45度",
                distance="极近距离",
                description="布满薄茧的手将手机放入电动车储物格，磨砂机身贴合掌心，哑光质感在阳光下不刺眼",
                product_reveal="特写定格，机身质感清晰",
                sfx_hint="指尖触碰机身细微摩擦声",
            ),
            SubShot(
                index=2, duration=5.0,
                shot_type="全景·缓推拉远",
                angle="正侧方平视",
                distance="远距离",
                description="盛夏正午柏油路热浪蒸腾，职场妈妈穿工装骑电动车，车后座绑着午饭，额头汗珠，眼神坚定",
                product_reveal="环境融合，手机在储物格自然带入",
                sfx_hint="电动车行驶声，远处蝉鸣",
            ),
            SubShot(
                index=3, duration=4.0,
                shot_type="中景·手持跟拍",
                angle="侧前方",
                distance="中距离",
                description="妈妈骑行到小区门口停下，掏出手机，屏幕在强光下清晰，操作无卡顿",
                product_reveal="自然带入，屏幕清晰可见",
                sfx_hint="消息提示音，指尖触控声",
            ),
            SubShot(
                index=4, duration=2.0,
                shot_type="特写·慢镜定格",
                angle="正面微仰",
                distance="近距离",
                description="手机静静躺在储物格，热浪微微扭曲画面边缘，慢镜留白",
                product_reveal="特写定格，机身在烈日下稳定呈现",
                sfx_hint="无，留白",
            ),
        ],
    ),

    # ── 第二段：暴雨 ────────────────────────────────────────────────────
    ShotTemplate(
        scene_type="暴雨",
        clip_index=1,
        duration=15.0,
        style_lock="低饱和写实质感，电影宽幅，哑光色调",
        color_temp="6000K",
        color_grade="冷灰蓝调为主，路灯暖光逐渐渗入",
        end_beat="慢镜留白1秒，雨水顺机身慢速流下",
        character_lock="人物面容、发型、气质全程保持一致，无变脸；穿着雨衣，贴合暴雨骑行场景",
        constraint="雨水效果连续，人物动作稳定不跳变，冷暖色调过渡不突兀",
        sub_shots=[
            SubShot(
                index=1, duration=4.0,
                shot_type="全景·手持晃动",
                angle="侧前方45度",
                distance="远距离",
                description="傍晚狂风骤雨，城市街道天色昏暗，大雨倾盆，路灯在雨幕中晕开暖黄光晕，路面积水反光",
                product_reveal="无",
                sfx_hint="狂风呼啸，暴雨声，远处雷声",
            ),
            SubShot(
                index=2, duration=3.5,
                shot_type="中景·手持跟拍",
                angle="正侧方",
                distance="中距离",
                description="妈妈穿深灰雨衣骑电动车在暴雨中前行，黑发丸子头被雨水打湿贴脸颊，神情专注，轮胎碾过积水溅起水花",
                product_reveal="无",
                sfx_hint="雨点击打雨衣声，轮胎碾水声",
            ),
            SubShot(
                index=3, duration=3.0,
                shot_type="特写·快推",
                angle="正上方俯拍",
                distance="极近距离",
                description="雨衣口袋中白色手机露出半截，密集雨点击打机身，水珠布满表面后沿边缘滑落，屏幕依然亮着显示来电",
                product_reveal="特写定格，防水性能自然呈现",
                sfx_hint="雨点密集击打声",
            ),
            SubShot(
                index=4, duration=2.5,
                shot_type="特写·慢镜定格",
                angle="机身侧面",
                distance="极近距离",
                description="雨水顺着手机机身缓慢流下，水珠在logo边缘晶莹剔透，机身洁白，慢镜留白",
                product_reveal="慢镜特写，机身质感与防水细节清晰",
                sfx_hint="水珠滴落细微声，渐弱",
            ),
        ],
    ),

    # ── 第三段：深夜 ────────────────────────────────────────────────────
    ShotTemplate(
        scene_type="深夜",
        clip_index=1,
        duration=15.0,
        style_lock="低饱和写实质感，电影宽幅，哑光色调",
        color_temp="2800K",
        color_grade="深夜暖黄调，低亮度，台灯侧光",
        end_beat="慢镜留白1秒，手机静躺桌面台灯侧光",
        character_lock="人物面容、发型、气质全程保持一致，无变脸；穿着居家服，贴合深夜室内场景",
        constraint="画面稳定，光影连续不跳变，机身质感统一",
        sub_shots=[
            SubShot(
                index=1, duration=4.0,
                shot_type="俯拍·缓慢下压",
                angle="正上方俯拍",
                distance="中距离",
                description="深夜书桌前，台灯昏黄，妈妈穿居家服，眉头微蹙，面前摆着工作文件和孩子作业，拿起手机查阅资料",
                product_reveal="自然带入，手机在桌面场景中融合",
                sfx_hint="笔尖划过纸张声，轻微翻页声",
            ),
            SubShot(
                index=2, duration=4.0,
                shot_type="特写·固定微推",
                angle="侧前方",
                distance="近距离",
                description="孩子趴在桌旁看手机讲解视频，妈妈一边看资料一边回复消息，手机后台多任务流畅运行",
                product_reveal="屏幕内容清晰，多任务流畅自然呈现",
                sfx_hint="轻微触控声，孩子低声提问",
            ),
            SubShot(
                index=3, duration=4.0,
                shot_type="近景·缓慢推进",
                angle="正前方略俯",
                distance="近距离",
                description="妈妈改完作业回复完最后一条消息，长舒一口气，将手机放在桌面，轻摸孩子头，眼底温柔，疲惫中带着坚定",
                product_reveal="手机放下动作自然，机身在台灯下低调呈现",
                sfx_hint="轻微叹气声，背景音乐渐入",
            ),
            SubShot(
                index=4, duration=3.0,
                shot_type="特写·固定慢镜",
                angle="机身侧面45度",
                distance="近距离",
                description="手机静静躺在桌面，台灯侧光，极简机身低调，慢镜留白",
                product_reveal="特写定格，机身质感在暖光下清晰",
                sfx_hint="无，留白",
            ),
        ],
    ),

    # ── 清晨 ─────────────────────────────────────────────────────────────
    ShotTemplate(
        scene_type="清晨",
        clip_index=1,
        duration=15.0,
        style_lock="低饱和写实质感，电影宽幅，哑光色调",
        color_temp="4800K",
        color_grade="清晨冷白调，薄雾漫射，轮廓光柔和",
        end_beat="慢镜留白1秒，晨光粒子悬浮定格",
        character_lock="人物面容、发型、气质全程保持一致，无变脸",
        constraint="画面稳定，晨雾效果连续，光影过渡不跳变",
        sub_shots=[
            SubShot(
                index=1, duration=5.0,
                shot_type="全景·固定",
                angle="正面平视",
                distance="远距离",
                description="清晨薄雾中的街道或院落，天色泛白，路灯尚未熄灭，远处树影朦胧，空气中有细密水汽",
                product_reveal="无",
                sfx_hint="鸟鸣声，远处车流隐约",
            ),
            SubShot(
                index=2, duration=5.0,
                shot_type="中景·缓推",
                angle="侧前方",
                distance="中距离",
                description="人物在晨光中出发，步伐沉稳，侧逆光勾勒轮廓，呼出的气息在冷空气中短暂可见",
                product_reveal="自然带入，随身携带",
                sfx_hint="脚步声，晨风声",
            ),
            SubShot(
                index=3, duration=5.0,
                shot_type="特写·慢镜定格",
                angle="俯拍45度",
                distance="近距离",
                description="晨光斜射在手机屏幕上，屏幕亮起显示时间，薄雾中机身轮廓清晰，慢镜留白",
                product_reveal="特写定格，晨光质感",
                sfx_hint="无，留白",
            ),
        ],
    ),

    # ── 黄昏 ─────────────────────────────────────────────────────────────
    ShotTemplate(
        scene_type="黄昏",
        clip_index=1,
        duration=15.0,
        style_lock="低饱和写实质感，电影宽幅，哑光色调",
        color_temp="3200K",
        color_grade="暖橙金调，逆光剪影，天际线渐变",
        end_beat="慢镜留白1秒，夕阳余晖定格",
        character_lock="人物面容、发型、气质全程保持一致，无变脸",
        constraint="逆光人物轮廓稳定，天空色彩过渡连续不跳变",
        sub_shots=[
            SubShot(
                index=1, duration=5.0,
                shot_type="全景·固定",
                angle="正面逆光",
                distance="远距离",
                description="黄昏时分，天际线橙红渐变，太阳低悬，远处建筑或山脊剪影清晰，云层被染成金橙色",
                product_reveal="无",
                sfx_hint="风声，远处城市低鸣",
            ),
            SubShot(
                index=2, duration=5.0,
                shot_type="中景·缓慢推进",
                angle="逆光侧面",
                distance="中距离",
                description="人物站在黄昏余晖中，逆光勾勒轮廓，面部处于阴影中，眼神望向远处，神情沉静",
                product_reveal="环境融合，手机在手中自然持握",
                sfx_hint="背景音乐渐入，低沉舒缓",
            ),
            SubShot(
                index=3, duration=5.0,
                shot_type="特写·慢镜定格",
                angle="侧面45度",
                distance="近距离",
                description="夕阳余晖打在手机机身上，金橙色光斑在机身表面流动，屏幕微亮，慢镜留白",
                product_reveal="特写定格，黄昏光感质感",
                sfx_hint="无，留白",
            ),
        ],
    ),

    # ── 大雪 ─────────────────────────────────────────────────────────────
    ShotTemplate(
        scene_type="大雪",
        clip_index=1,
        duration=15.0,
        style_lock="低饱和写实质感，电影宽幅，哑光色调",
        color_temp="6800K",
        color_grade="冷白调，雪光漫反射，低对比柔和",
        end_beat="慢镜留白1秒，雪花飘落定格",
        character_lock="人物面容、发型、气质全程保持一致，无变脸",
        constraint="雪花粒子连续不跳帧，人物动作稳定，雪地反光统一",
        sub_shots=[
            SubShot(
                index=1, duration=5.0,
                shot_type="全景·固定",
                angle="正面平视",
                distance="远距离",
                description="大雪纷飞，街道或旷野被白雪覆盖，雪花密集飘落，能见度降低，远处轮廓模糊",
                product_reveal="无",
                sfx_hint="风雪声，脚踩积雪的嘎吱声",
            ),
            SubShot(
                index=2, duration=5.0,
                shot_type="中景·手持跟拍",
                angle="侧前方",
                distance="中距离",
                description="人物在大雪中前行，雪花落在肩头和头发上，呼出白雾，步伐坚定，眼神专注",
                product_reveal="自然带入，手机在口袋或手中",
                sfx_hint="脚步声，风雪声",
            ),
            SubShot(
                index=3, duration=5.0,
                shot_type="特写·慢镜定格",
                angle="俯拍",
                distance="近距离",
                description="雪花落在手机机身上缓慢融化，屏幕依然亮着，雪光漫反射下机身洁白，慢镜留白",
                product_reveal="特写定格，雪中稳定运行",
                sfx_hint="无，留白",
            ),
        ],
    ),

    # ── 室内对峙 ─────────────────────────────────────────────────────────
    ShotTemplate(
        scene_type="室内对峙",
        clip_index=1,
        duration=15.0,
        style_lock="低饱和写实质感，电影宽幅，哑光色调",
        color_temp="3800K",
        color_grade="暖调暗调，局部硬光，阴影压重",
        end_beat="慢镜留白1秒，人物眼神定格",
        character_lock="人物面容、发型、气质全程保持一致，无变脸；双方服化道各自锁定",
        constraint="双人构图稳定，视线交汇逻辑连贯，光影不跳变",
        sub_shots=[
            SubShot(
                index=1, duration=4.0,
                shot_type="全景·固定",
                angle="正面平视",
                distance="远距离",
                description="室内空间，两人相对而立，空间压迫感强，背景简洁，光线从侧面打入，阴影分明",
                product_reveal="无",
                sfx_hint="室内环境音，低频压迫感",
            ),
            SubShot(
                index=2, duration=5.0,
                shot_type="中景·正反打",
                angle="侧面交替",
                distance="中距离",
                description="两人正反打切换，面部表情克制，眼神交锋，嘴唇微动，情绪在压制与对抗之间拉扯",
                product_reveal="无",
                sfx_hint="无，静默压迫",
            ),
            SubShot(
                index=3, duration=3.5,
                shot_type="特写·微推",
                angle="正面",
                distance="近距离",
                description="主角眼神特写，瞳孔聚焦，眉头微蹙，嘴角克制，内心波澜不显于表面",
                product_reveal="无",
                sfx_hint="心跳低频音效，渐强",
            ),
            SubShot(
                index=4, duration=2.5,
                shot_type="特写·慢镜定格",
                angle="侧面",
                distance="近距离",
                description="人物侧脸慢镜定格，光影在面部形成明暗分割，留白",
                product_reveal="无",
                sfx_hint="无，留白",
            ),
        ],
    ),

    # ── 奔跑追逐 ─────────────────────────────────────────────────────────
    ShotTemplate(
        scene_type="奔跑追逐",
        clip_index=1,
        duration=15.0,
        style_lock="低饱和写实质感，电影宽幅，哑光色调",
        color_temp="5500K",
        color_grade="自然日光调，动态模糊强化速度感",
        end_beat="慢镜留白1秒，奔跑定格喘息瞬间",
        character_lock="人物面容、发型、气质全程保持一致，无变脸",
        constraint="动态模糊连续，人物骨架不畸变，背景运动方向统一",
        sub_shots=[
            SubShot(
                index=1, duration=4.0,
                shot_type="全景·手持跟拍",
                angle="侧面跟随",
                distance="中距离",
                description="人物在街道或走廊中全力奔跑，手持跟拍强化晃动感，背景虚化拉伸，速度感强烈",
                product_reveal="无",
                sfx_hint="急促脚步声，喘息声，风声",
            ),
            SubShot(
                index=2, duration=5.0,
                shot_type="中景·前置跟拍",
                angle="正面",
                distance="中距离",
                description="正面跟拍奔跑中的人物，面部表情紧张专注，汗水，眼神坚定，背景快速后退",
                product_reveal="无",
                sfx_hint="心跳声渐强，脚步声",
            ),
            SubShot(
                index=3, duration=4.0,
                shot_type="特写·慢镜",
                angle="侧面",
                distance="近距离",
                description="慢镜捕捉奔跑中的细节——脚踏地面溅起水花或尘土，手臂摆动，衣物随风飘动",
                product_reveal="无",
                sfx_hint="慢镜音效，低频拉伸",
            ),
            SubShot(
                index=4, duration=2.0,
                shot_type="特写·慢镜定格",
                angle="正面",
                distance="近距离",
                description="人物停下瞬间，大口喘气，眼神扫视四周，慢镜留白",
                product_reveal="无",
                sfx_hint="无，留白",
            ),
        ],
    ),

    # ── 古风庭院 ─────────────────────────────────────────────────────────
    ShotTemplate(
        scene_type="古风庭院",
        clip_index=1,
        duration=15.0,
        style_lock="低饱和古风质感，电影宽幅，哑光色调，水墨留白",
        color_temp="4500K",
        color_grade="青灰冷调，墨绿点缀，素白底色",
        end_beat="慢镜留白1秒，落花或烟雾定格",
        character_lock="人物面容、发型、服化道全程保持一致，无变脸无换装",
        constraint="古风服饰细节稳定，庭院空间透视不变形，光影连续",
        sub_shots=[
            SubShot(
                index=1, duration=5.0,
                shot_type="全景·缓推",
                angle="正面平视",
                distance="远距离",
                description="古风庭院，青石板路，廊柱朱红，院中有古树或假山，薄雾或落花点缀，空气感强",
                product_reveal="无",
                sfx_hint="风吹树叶声，远处鸟鸣",
            ),
            SubShot(
                index=2, duration=5.0,
                shot_type="中景·环绕",
                angle="侧面缓慢环绕",
                distance="中距离",
                description="古装人物立于庭院中，衣袂随风微动，神情清冷，眼神望向远处，仪态克制",
                product_reveal="无",
                sfx_hint="古筝或琵琶背景音，低沉",
            ),
            SubShot(
                index=3, duration=5.0,
                shot_type="特写·慢镜定格",
                angle="俯拍",
                distance="近距离",
                description="落花飘落在青石板上，或烟雾在庭院中弥散，慢镜捕捉细节，留白",
                product_reveal="无",
                sfx_hint="无，留白",
            ),
        ],
    ),

    # ── 城市夜景 ─────────────────────────────────────────────────────────
    ShotTemplate(
        scene_type="城市夜景",
        clip_index=1,
        duration=15.0,
        style_lock="低饱和写实质感，电影宽幅，哑光色调",
        color_temp="3500K",
        color_grade="城市暖光点缀冷蓝夜空，霓虹反光，湿地倒影",
        end_beat="慢镜留白1秒，城市灯光虚化定格",
        character_lock="人物面容、发型、气质全程保持一致，无变脸",
        constraint="夜景光源稳定，人物面部补光连续，背景灯光不跳变",
        sub_shots=[
            SubShot(
                index=1, duration=5.0,
                shot_type="全景·航拍缓推",
                angle="俯拍45度",
                distance="远距离",
                description="城市夜景俯瞰，万家灯火，道路车流形成光轨，建筑轮廓在夜色中清晰，天际线壮阔",
                product_reveal="无",
                sfx_hint="城市低频环境音",
            ),
            SubShot(
                index=2, duration=5.0,
                shot_type="中景·固定",
                angle="正面平视",
                distance="中距离",
                description="人物站在城市高处或街头，背后是城市夜景，霓虹灯光在面部形成冷暖交织的光斑",
                product_reveal="自然带入，手机屏幕亮光与城市灯光呼应",
                sfx_hint="背景音乐，城市低鸣",
            ),
            SubShot(
                index=3, duration=5.0,
                shot_type="特写·慢镜定格",
                angle="侧面",
                distance="近距离",
                description="手机屏幕在夜色中亮起，城市灯光在机身上形成虚化光斑，慢镜留白",
                product_reveal="特写定格，夜间屏幕清晰",
                sfx_hint="无，留白",
            ),
        ],
    ),

    # ── 山顶旷野 ─────────────────────────────────────────────────────────
    ShotTemplate(
        scene_type="山顶旷野",
        clip_index=1,
        duration=15.0,
        style_lock="低饱和写实质感，电影宽幅，哑光色调",
        color_temp="5800K",
        color_grade="自然日光，高饱和天空，低饱和大地，强对比",
        end_beat="慢镜留白1秒，风吹衣物定格",
        character_lock="人物面容、发型、气质全程保持一致，无变脸",
        constraint="天空云层运动连续，人物站位稳定，风力效果统一",
        sub_shots=[
            SubShot(
                index=1, duration=5.0,
                shot_type="全景·航拍",
                angle="俯拍缓降",
                distance="远距离",
                description="山顶或旷野，天地辽阔，云层低压，风吹草动，远处山脉连绵，空间感极强",
                product_reveal="无",
                sfx_hint="强风声，远处鹰鸣",
            ),
            SubShot(
                index=2, duration=5.0,
                shot_type="中景·固定",
                angle="正面逆光",
                distance="中距离",
                description="人物站在山顶，迎风而立，衣物和头发被风吹动，逆光勾勒轮廓，眼神望向远方",
                product_reveal="环境融合，手机在手中自然持握",
                sfx_hint="风声，背景音乐渐入",
            ),
            SubShot(
                index=3, duration=5.0,
                shot_type="特写·慢镜定格",
                angle="侧面",
                distance="近距离",
                description="风吹衣物慢镜定格，手机在手中稳定，信号满格，慢镜留白",
                product_reveal="特写定格，户外稳定运行",
                sfx_hint="无，留白",
            ),
        ],
    ),

    # ── 医院走廊 ─────────────────────────────────────────────────────────
    ShotTemplate(
        scene_type="医院走廊",
        clip_index=1,
        duration=15.0,
        style_lock="低饱和写实质感，电影宽幅，哑光色调",
        color_temp="5000K",
        color_grade="冷白荧光调，低饱和，压抑克制",
        end_beat="慢镜留白1秒，走廊尽头虚化定格",
        character_lock="人物面容、发型、气质全程保持一致，无变脸",
        constraint="走廊透视稳定，荧光灯光连续，人物动作不跳帧",
        sub_shots=[
            SubShot(
                index=1, duration=4.0,
                shot_type="全景·固定",
                angle="正面平视",
                distance="远距离",
                description="医院走廊，荧光灯冷白，地面反光，走廊尽头模糊，偶有医护人员经过，空间压迫感强",
                product_reveal="无",
                sfx_hint="走廊回声，远处广播声",
            ),
            SubShot(
                index=2, duration=6.0,
                shot_type="中景·手持跟拍",
                angle="侧后方",
                distance="中距离",
                description="人物在走廊中快步行走，步伐急促，手中紧握手机，面部表情焦虑克制",
                product_reveal="自然带入，手机紧握在手",
                sfx_hint="脚步声，心跳低频",
            ),
            SubShot(
                index=3, duration=3.0,
                shot_type="特写·固定",
                angle="正面",
                distance="近距离",
                description="人物在走廊椅子上坐下，低头看手机，屏幕亮起，荧光灯冷光打在面部",
                product_reveal="屏幕清晰，等待中的陪伴",
                sfx_hint="环境音渐弱",
            ),
            SubShot(
                index=4, duration=2.0,
                shot_type="特写·慢镜定格",
                angle="俯拍",
                distance="近距离",
                description="手机屏幕在冷白荧光下亮着，慢镜留白",
                product_reveal="特写定格",
                sfx_hint="无，留白",
            ),
        ],
    ),

    # ── 第四段：结尾闭环 ─────────────────────────────────────────────────
    ShotTemplate(
        scene_type="结尾闭环",
        clip_index=1,
        duration=15.0,
        style_lock="低饱和写实质感，电影宽幅，哑光色调",
        color_temp="3200K",
        color_grade="闪回色温递变6500K→6000K→2800K，定格统一回暖调",
        end_beat="渐暗溶出，文字渐显后LOGO低调出现",
        character_lock="人物面容、发型、气质全程保持一致，无变脸；闪回段衣服随对应场景，定格画面穿工装",
        constraint="闪回节奏统一，定格画面稳定，渐暗连续不跳变，文字清晰可读",
        sub_shots=[
            SubShot(
                index=1, duration=4.5,
                shot_type="特写·快切闪回",
                angle="正面",
                distance="近距离",
                description="三段场景快速闪回——烈日下的眼神、暴雨中的眼神、深夜的眼神，同一张脸，同一个坚定",
                product_reveal="无",
                sfx_hint="三段环境音依次闪入，节奏紧凑",
            ),
            SubShot(
                index=2, duration=5.5,
                shot_type="全景·缓慢拉远",
                angle="正前方平视",
                distance="中距离→远距离",
                description="同一名妈妈穿工装骑电动车，孩子坐后座，阳光打在她背上，手机在储物格里，画面渐暗",
                product_reveal="环境融合，手机在储物格自然带入，与开篇呼应",
                sfx_hint="背景音乐渐强后渐弱",
            ),
            SubShot(
                index=3, duration=5.0,
                shot_type="字幕·渐显溶出",
                angle="无",
                distance="无",
                description="画面渐暗，文字渐显：「每天，陪你跨越山海。」「vivo Y600 Pro 万级长续航」，品牌LOGO低调出现，收",
                product_reveal="LOGO低调呈现，品牌收尾",
                sfx_hint="手机点亮轻微提示音，结尾干净",
            ),
        ],
    ),
]


# ---------------------------------------------------------------------------
# 检索接口
# ---------------------------------------------------------------------------

def get_templates_for_scene(scene_type: str) -> list[ShotTemplate]:
    """Return all templates matching the given scene_type."""
    return [t for t in SHOT_TEMPLATE_LIBRARY if t.scene_type == scene_type]


def get_all_scene_types() -> list[str]:
    seen: list[str] = []
    for t in SHOT_TEMPLATE_LIBRARY:
        if t.scene_type not in seen:
            seen.append(t.scene_type)
    return seen


def render_all_prompts() -> dict[str, str]:
    """Return {scene_type: seedance_prompt} for all templates."""
    result: dict[str, str] = {}
    for t in SHOT_TEMPLATE_LIBRARY:
        key = f"{t.scene_type}_clip{t.clip_index}"
        result[key] = t.to_seedance_prompt()
    return result

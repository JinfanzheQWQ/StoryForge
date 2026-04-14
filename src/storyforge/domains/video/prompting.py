from __future__ import annotations

import re

from storyforge.domains.novel.contracts import CharacterVoiceProfile, NovelPackage
from storyforge.domains.video.contracts import CharacterVisualProfile, VideoSegment


class VideoPromptingMixin:
    CHARACTER_SHEET_LAYOUT_PROMPT = (
        "统一三视图模板 SF-TURN-01：所有角色定妆图必须使用完全相同的横版 16:9 白底三视图版式，"
        "同一项目内所有角色必须保持同一种美术风格、同一种线条粗细、同一种上色方式和同一种柔和光照，"
        "不得因角色身份、性别或剧情气质改变构图、画风、镜头焦段或渲染质感。"
        "背景必须是纯白色，不要场景、不要道具陈列、不要灰底网格、不要信息格、不要色卡、不要材质块。"
        "画面顶部只允许出现角色中文姓名；不得写性别、身份、职业、角色定位、英文标签、编号、水印或说明文字。"
        "画面主体固定为三栏等宽全身站姿：左栏正面，中栏左侧面，右栏背面。"
        "三视图都必须平视，双脚完整入画，脚底对齐同一基准线，人物高度和缩放比例完全一致，"
        "双臂自然下垂或轻微离开身体，避免夸张动作。"
        "统一采用干净高级的动画电影概念设定稿风格，柔和赛璐璐上色，低饱和自然色彩，清晰轮廓线，"
        "避免有的角色偏写实、有的角色偏二次元、有的角色偏照片或海报。"
        "同一张图里只能是同一个角色的正面、左侧面和背面参考，不得出现第二个独立角色或剧情场景。"
    )

    def _build_visual_bible_user_prompt(self, novel_package: NovelPackage) -> str:
        allowed_names = "、".join(item.name for item in novel_package.outline.characters) or "无"
        character_blocks = "\n".join(
            (
                f"- 角色名：{item.name}\n"
                f"  性别：{item.gender}\n"
                f"  身份：{item.role}\n"
                f"  欲望：{item.desire}\n"
                f"  冲突：{item.conflict}\n"
                f"  视觉锚点：{'、'.join(item.visual_signature) or '无'}\n"
                f"  角色图提示：{item.image_prompt or '无'}"
            )
            for item in novel_package.outline.characters
        )
        motifs = "、".join(novel_package.outline.visual_motifs) or "无"
        return f"""
请基于以下小说角色资料输出角色视觉卡。

- 小说标题：{novel_package.outline.title}
- 视觉母题：{motifs}
- 角色原名白名单：{allowed_names}
- 角色资料：
{character_blocks}

硬性要求：
1. `characters` 数量必须与角色原名白名单一致
2. `name` 字段只能从白名单中选择，不得改名，不得把角色写成新名字
3. 不得新增、合并或删除主要角色
4. 输出必须能直接用于角色定妆卡生成，强调稳定年龄感、稳定体型和稳定服装轮廓
5. 不要把角色写成“主角 / 男主 / 女主 / 神秘人”等泛称
6. 每个角色必须继承小说角色卡中的性别，`gender` 不得凭空改写
7. `appearance` 和 `portrait_prompt` 必须明确写出性别、年龄段、身高体态和服装轮廓
8. `portrait_prompt` 只描述人物特征，不要自行指定与统一角色定妆卡冲突的构图、场景或镜头
""".strip()

    def _build_segment_planner_user_prompt(self, novel_package: NovelPackage) -> str:
        allowed_names = "、".join(item.name for item in novel_package.outline.characters) or "无"
        chapter_blocks = "\n\n".join(
            self._build_chapter_segment_directive(novel_package, chapter_number=item.number)
            for item in novel_package.outline.chapters
        )
        return f"""
请基于以下小说大纲和章节草稿，拆出多个视频片段。

- 小说标题：{novel_package.outline.title}
- 角色原名白名单：{allowed_names}
- 只能使用小说中已存在的角色原名，不得改名，不得新增角色
- 每个章节都必须至少产出 1 个片段
- 视频“段”是章节内部的叙事切片，不是章节本身；同一章节可以拆成 1 段、2 段、3 段或更多
- 每章拆成几段必须由你根据该章正文内容自行判断，依据包括：事件推进、场景切换、时间跳跃、情绪转折、镜头密度、对白密度
- 不要把章节硬压成固定段数，也不要为了凑平均数机械切段
- 每个片段除画面字段外，还必须输出可直接给 Seedance 使用的旁白、角色对白、环境音、音乐方向和时间节拍
- 每个片段的 `duration_seconds` 必须由你根据剧情密度自行判断，范围限定在 {self.PLANNER_MIN_DURATION_SECONDS}-{self.SEEDANCE_MAX_DURATION_SECONDS} 秒
- 不要把所有片段都机械写成同一个时长；对白密集、动作更复杂、信息量更大的片段可以更长
- 如果你无法判断，就优先接近 {self.segment_duration_seconds} 秒
- 你必须按中文自然口播语速估算音频长度，按每秒约 {self.SPEECH_CHARS_PER_SECOND} 个中文字计算可口播字数
- 5 秒片段只能放极短句，总旁白 + 对白 + 硬字幕文案约 15 字以内；8 秒片段可放一句短对白加少量旁白，约 24 字以内；12 秒片段最多两句短对白，约 36 字以内
- 如果旁白、对白或硬字幕超过当前时长可说完的字数，必须拆成下一个片段，不得硬塞进同一段
- `subtitle_lines` 必须只写本片段实际能在音频里说完的文字，不能提前打印还没说完的句子
- `timed_beats` 必须明确每一句旁白或对白在几秒到几秒说出，不能只写泛泛的镜头节奏
- 每个片段必须输出 `transition_hint`，取值只能是 `continue` / `cut` / `auto`
- 片段必须覆盖全部章节，`chapter_number` 必须与来源章节一致
- 必须严格复刻章节正文已经发生的事件、情绪和对白关系，不得自行改写关键情节、改变角色关系或新增冲突
- 如果正文是告白、表白、对峙、争吵、谈判、审问、双人对话，`involved_characters` 必须同时包含对话/关系双方，不能只写一个角色
- `dialogue_lines` 中出现的所有角色，都必须进入 `involved_characters`
- `scene_prompt`、`start_frame_prompt`、`end_frame_prompt` 必须写清每个出镜角色的位置、动作和相互关系

章节拆分依据：
{chapter_blocks}
""".strip()

    def _build_chapter_segment_directive(
        self,
        novel_package: NovelPackage,
        chapter_number: int,
    ) -> str:
        chapter = next(
            item for item in novel_package.outline.chapters if item.number == chapter_number
        )
        draft = next(
            (item for item in novel_package.chapters if item.number == chapter_number),
            None,
        )
        featured = "、".join(chapter.featured_characters) or "无"
        beats = "；".join(chapter.beats) or chapter.summary
        excerpt = self._excerpt_text(draft.markdown if draft else chapter.summary, max_chars=1400)
        return (
            f"- 第 {chapter.number} 章《{chapter.title}》\n"
            "  该章应由模型自行判断拆成几段\n"
            f"  章节目标：{chapter.goal}\n"
            f"  章节摘要：{chapter.summary}\n"
            f"  关键冲突：{chapter.key_conflict}\n"
            f"  重点角色：{featured}\n"
            f"  场景节拍：{beats}\n"
            f"  正文摘录：{excerpt}"
        )

    def _excerpt_text(self, text: str, max_chars: int = 220) -> str:
        compact = re.sub(r"\s+", " ", text).strip()
        if len(compact) <= max_chars:
            return compact
        return compact[: max_chars - 1].rstrip() + "…"

    def _chunk_text(self, text: str, chunk_count: int) -> list[str]:
        units = self._split_text_units(text)
        if not units:
            return ["" for _ in range(chunk_count)]
        return [
            "".join(chunk).strip()
            for chunk in self._chunk_list(units, chunk_count)
        ]

    def _split_text_units(self, text: str) -> list[str]:
        cleaned = text.strip()
        if not cleaned:
            return []
        units = re.split(r"(?<=[。！？!?；;])", cleaned)
        normalized = [item.strip() for item in units if item.strip()]
        return normalized or [cleaned]

    def _extract_beat_descriptions(self, beats: list[str]) -> list[str]:
        descriptions: list[str] = []
        for beat in beats:
            if not beat.strip():
                continue
            _, separator, remainder = beat.partition("：")
            if not separator:
                _, separator, remainder = beat.partition(":")
            descriptions.append((remainder if separator else beat).strip())
        return descriptions

    def _retime_beat_descriptions(
        self,
        descriptions: list[str],
        duration_seconds: int,
    ) -> list[str]:
        if not descriptions:
            return [f"0-{duration_seconds}秒：保持当前片段的核心动作与情绪推进。"]

        grouped_descriptions = descriptions
        if len(descriptions) > duration_seconds:
            grouped_descriptions = [
                "；".join(chunk)
                for chunk in self._chunk_list(descriptions, duration_seconds)
                if chunk
            ]

        beat_count = len(grouped_descriptions)
        timed_beats: list[str] = []
        for index, description in enumerate(grouped_descriptions):
            start = round(index * duration_seconds / beat_count)
            end = round((index + 1) * duration_seconds / beat_count)
            if index == beat_count - 1:
                end = duration_seconds
            if end <= start:
                end = min(duration_seconds, start + 1)
            if start == end:
                start = max(0, end - 1)
            timed_beats.append(f"{start}-{end}秒：{description}")
        return timed_beats

    def _fallback_subsegment_narration(
        self,
        summary: str,
        segment_index: int,
        segment_count: int,
    ) -> str:
        return f"{summary}（当前为第 {segment_index}/{segment_count} 段）"

    def _stylize_character_prompt(self, prompt: str) -> str:
        return (
            "原创虚构角色白底三视图参考，风格化概念插画，非真人摄影，动画电影质感，"
            "角色一致性强，正面、左侧面和背面设定清晰，"
            f"{prompt}"
        )

    def _build_character_sheet_prompt(
        self,
        name: str,
        role: str,
        gender: str,
        appearance: str,
        outfit: str,
        source_prompt: str,
    ) -> str:
        source_hint = source_prompt.strip()
        extra_hint = (
            f"补充人物描述：{source_hint}。"
            if source_hint
            else ""
        )
        return (
            "原创虚构角色白底三视图，单角色，非真人摄影，非写实照片，"
            "偏影视概念设定与动画电影角色设计，prompt 尽量简洁，只根据姓名和人物描述生成。"
            f"{self.CHARACTER_SHEET_LAYOUT_PROMPT}"
            f"画面唯一可见文字：{name}。"
            f"人物描述：{appearance}；{outfit}。"
            f"内部理解参考，不要写成画面文字：性别 {gender}；叙事身份 {role}。"
            "必须保持同一张脸、同一发型、同一服装、同一年龄感、同一身材比例，"
            "锁定肩宽、头身比、四肢比例和体脂观感，不要随机改设定。"
            "不要改成电影剧照、动态打斗、半身大头照、单独肖像、海报、全景环境图、复杂场景或设计信息板。"
            "不要因为镜头或姿势变化把角色画得更老、更幼、更胖、更瘦、更壮或更矮。"
            "只保留设定中明确出现的道具，不要额外添加盔甲、外骨骼、枪械、刀剑、奇幻饰品或科幻装备。"
            "禁止在画面中出现“男、女、主角、配角、身份、职业、年龄、性格、主色、材质”等文字标签。"
            f"{extra_hint}"
        )

    def _build_character_consistency_notes(
        self,
        profile: CharacterVisualProfile,
    ) -> str:
        palette = "、".join(profile.color_palette) if profile.color_palette else "未指定"
        return (
            f"{profile.name} | 性别：{profile.gender} | 外观：{profile.appearance} | 服装：{profile.outfit} | "
            f"主配色：{palette} | 年龄感、脸型、肩宽、头身比、四肢比例和体型必须稳定，"
            "不要忽老忽幼、忽胖忽瘦、忽高忽矮、忽壮忽弱"
        )

    def _build_scene_character_lock(
        self,
        segment: VideoSegment,
        profile_map: dict[str, CharacterVisualProfile],
    ) -> str:
        locked_profiles: list[str] = []
        for name in segment.involved_characters:
            profile = profile_map.get(name)
            if profile is None:
                continue
            palette = "、".join(profile.color_palette) if profile.color_palette else "按设定控制"
            locked_profiles.append(
                f"{name}：性别 {profile.gender}；外观 {profile.appearance}；服装 {profile.outfit}；主配色 {palette}；"
                "同一年龄感、同一体型、同一肩宽、同一头身比、同一四肢比例、同一脸型轮廓"
            )

        if not locked_profiles:
            return (
                "若角色出镜，保持与参考设定图一致的人脸结构、发型、服装层次、主配色、"
                "年龄感、体型、肩宽和四肢比例，不要忽胖忽瘦、忽老忽幼。"
            )

        return (
            "角色锁定要求："
            + " | ".join(locked_profiles)
            + "。严格保持与参考设定图一致的人脸结构、发型、服装层次、主配色、年龄感、体型、肩宽、头身比和四肢比例，"
            "多人同屏时不得省略任何一个 involved_characters，"
            "不要把角色画得更老、更幼、更胖、更瘦、更壮、更矮或比例失真，"
            "不要新增盔甲、额外武器、外骨骼、奇幻饰品或不相关时代元素。"
        )

    def _stylize_scene_prompt(
        self,
        prompt: str,
        segment: VideoSegment,
        character_lock: str,
    ) -> str:
        characters = "、".join(segment.involved_characters) or "环境为主"
        return (
            "原创虚构场景分镜，风格化概念插画，非真人摄影，"
            "优先展示环境、光线和镜头调度，避免近景人像特写，"
            "若 involved_characters 有 2 人或以上，则这些角色必须同时出镜，不要只画一个人，"
            "每个 involved_characters 都必须按对应参考设定图还原，"
            "若角色出镜，必须保持稳定年龄感、稳定体型、稳定肩宽、稳定四肢比例和稳定脸型轮廓，"
            f"角色：{characters}，{character_lock}，{prompt}"
        )

    def _stylize_frame_prompt(
        self,
        prompt: str,
        segment: VideoSegment,
        frame_type: str,
        character_lock: str,
    ) -> str:
        characters = "、".join(segment.involved_characters) or "环境为主"
        return (
            f"{frame_type}，原创虚构电影分镜，风格化概念插画，非真人摄影，"
            f"角色：{characters}，若有双人或多人出镜要求则必须全部画出，且全部按对应参考设定图还原，{character_lock}，"
            f"保持场景连续性、稳定年龄感、稳定体型、稳定肩宽和稳定四肢比例，{prompt}"
        )

    def _build_default_timed_beats(
        self,
        beat: str,
        chapter_summary: str,
        narration: str,
        dialogue_lines: list[str],
        sound_effects: list[str],
        duration_seconds: int | None = None,
    ) -> list[str]:
        effective_duration = max(
            duration_seconds or self.segment_duration_seconds,
            self.PLANNER_MIN_DURATION_SECONDS,
        )
        dialogue = dialogue_lines[0] if dialogue_lines else "本段无明确对白，以旁白和动作推进。"
        ambience = "、".join(sound_effects[:2]) if sound_effects else "低频环境氛围声"
        return [
            f"[0s-2s] 建立环境与角色位置，画面先交代 {beat}，音频先铺 {ambience}。",
            f"[2s-4s] 旁白推进：{narration}",
            f"[4s-{effective_duration}s] 角色动作或情绪收束，关键对白：{dialogue}；结尾回到 {chapter_summary} 的悬念感。",
        ]

    def _build_seedance_clip_prompt(self, segment: VideoSegment) -> str:
        speech_budget = segment.duration_seconds * self.SPEECH_CHARS_PER_SECOND
        lines = [
            "请生成带原生音频的中文剧情短视频片段。",
            f"片段标题：{segment.title}",
            f"时长：{segment.duration_seconds} 秒。",
            f"语速预算：中文口播总量控制在约 {speech_budget} 字以内，所有对白和旁白必须在片尾前自然说完。",
            f"角色：{'、'.join(segment.involved_characters) or '环境为主'}。",
            f"画面主提示：{segment.scene_prompt}",
            f"旁白：{segment.narration}",
        ]
        if segment.dialogue_lines:
            lines.append("角色对白：")
            lines.extend(f"- {line}" for line in segment.dialogue_lines)
        else:
            lines.append("角色对白：")
            lines.append("- 本段无角色对白，只保留旁白、环境音和镜头动作。")
        if segment.character_voice_notes:
            lines.append("角色音色锁定：")
            lines.extend(f"- {item}" for item in segment.character_voice_notes)
        if segment.sound_effects:
            lines.append("环境音/拟音：")
            lines.extend(f"- {item}" for item in segment.sound_effects)
        if segment.music_direction:
            lines.append(f"音乐方向：{segment.music_direction}")
        if segment.timed_beats:
            lines.append("时间节拍：")
            lines.extend(f"- {item}" for item in segment.timed_beats)
        if self.seedance_config.subtitle_mode == "burned_in":
            lines.append(f"硬字幕样式：{self.seedance_config.subtitle_style}")
            subtitle_lines = segment.subtitle_lines or self._build_subtitle_lines(
                narration=segment.narration,
                dialogue_lines=segment.dialogue_lines,
                timed_beats=segment.timed_beats,
            )
            if subtitle_lines:
                lines.append("硬字幕文案：")
                lines.extend(f"- {item}" for item in subtitle_lines)
            lines.append("请把上述字幕直接烧录到画面底部，不要输出外挂字幕文件。")
            lines.append("硬字幕必须与实际口播同步出现，不要提前打印尚未说出口的文字。")
            lines.append("如果时长不足，优先压缩停顿和删减非字幕口播，不要截断对白或字幕。")
            lines.append("要求口播、对白、环境音与镜头动作自然同步。")
        else:
            lines.append("要求口播、对白、环境音与镜头动作自然同步，不要额外添加字幕。")
        lines.append(
            "同一角色跨镜头保持稳定音色、说话节奏、年龄感、体型、肩宽和四肢比例，不要忽老忽胖、忽瘦忽壮或突然变声。"
        )
        return "\n".join(lines)

    def _build_segment_voice_notes(
        self,
        involved_characters: list[str],
        voice_map: dict[str, CharacterVoiceProfile],
        existing_notes: list[str] | None = None,
    ) -> list[str]:
        if existing_notes:
            return list(existing_notes)
        notes: list[str] = []
        for name in involved_characters:
            voice_profile = voice_map.get(name)
            if voice_profile is not None:
                notes.append(self._format_voice_note(name, voice_profile))
            else:
                notes.append(
                    f"{name}：跨片段保持相同音色、说话速度、情绪基调和年龄感，不要突然变声"
                )
        return notes

    def _format_voice_note(
        self,
        name: str,
        voice_profile: CharacterVoiceProfile,
    ) -> str:
        parts = [
            f"整体声音：{voice_profile.resolved_voice_style()}",
            f"音色：{voice_profile.timbre or '保持已建立音色'}",
            f"语速：{voice_profile.speaking_rate or '稳定中速'}",
            f"情绪基线：{voice_profile.emotional_baseline or '稳定克制'}",
        ]
        if voice_profile.accent_or_texture:
            parts.append(f"口音/质感：{voice_profile.accent_or_texture}")
        if voice_profile.dialogue_delivery:
            parts.append(f"说话方式：{voice_profile.dialogue_delivery}")
        if voice_profile.forbidden_voice_changes:
            parts.append(
                "禁止变化：" + "、".join(voice_profile.forbidden_voice_changes)
            )
        parts.append("跨片段保持同一角色音色身份，不要突然换腔、变调或变成年龄感明显不同的声音")
        return f"{name}：" + "；".join(parts)

    def _build_subtitle_lines(
        self,
        narration: str,
        dialogue_lines: list[str],
        timed_beats: list[str],
    ) -> list[str]:
        subtitle_lines: list[str] = []
        subtitle_lines.extend(dialogue_lines[:2])
        if narration:
            subtitle_lines.append(narration)
        if not subtitle_lines and timed_beats:
            subtitle_lines.extend(timed_beats[:2])
        return subtitle_lines[:3]

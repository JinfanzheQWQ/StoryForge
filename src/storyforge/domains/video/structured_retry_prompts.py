from __future__ import annotations

import re
from typing import TypeVar

from pydantic import BaseModel

from storyforge.agents.base import PromptRequest
from storyforge.domains.video.errors import (
    SegmentActionSplitRequiredError,
    SegmentSpeechSplitRequiredError,
)


StructuredModelT = TypeVar("StructuredModelT", bound=BaseModel)


class VideoStructuredRetryPromptMixin:
    """Builds task-specific retry prompts for structured video generation."""

    def _build_repair_retry_request(
        self,
        *,
        request: PromptRequest,
        schema: type[StructuredModelT],
        attempt: int,
        last_error: Exception | None,
    ) -> PromptRequest:
        task_name = str(request.metadata.get("task", "") or "").strip()
        normalized_error = " ".join(str(last_error or "").split()).strip()
        if task_name == "video-chapter-event-repair" and "关键事件" in normalized_error and "过于粗" in normalized_error:
            offending_event_id = ""
            match = re.search(r"关键事件\s+(ch\d{2}-ev\d{2})", normalized_error)
            if match is not None:
                offending_event_id = match.group(1).strip()
            metadata = dict(request.metadata)
            if offending_event_id:
                metadata["offending_event_id"] = offending_event_id
            retry_prompt = request.user_prompt
            retry_prompt += (
                f"\n\n上一次修复输出未通过结构化校验。这是第 {attempt} 次尝试。"
                f" 失败原因：{normalized_error}。"
            )
            if offending_event_id:
                retry_prompt += (
                    f" 本次只优先修 `{offending_event_id}` 及其后续编号，"
                    "不要回头大改前面已经合理的 event。"
                )
            retry_prompt += (
                " 如果当前失败项不是章节首尾 event，就必须压到 1-2 个推进点；"
                "如果压不住，就直接拆成两个连续 event，并把后续 event_id 顺延。"
                " 中间 event 不要再把问句、回答、动作结果三连塞在一起。"
                " 不要解释，不要输出 Markdown 代码块，不要漏字段。"
            )
            return PromptRequest(
                system_prompt=request.system_prompt,
                user_prompt=retry_prompt,
                metadata=metadata,
            )
        if task_name == "video-chapter-event-split-repair" and "关键事件" in normalized_error and "过于粗" in normalized_error:
            offending_event_id = ""
            match = re.search(r"关键事件\s+(ch\d{2}-ev\d{2})", normalized_error)
            if match is not None:
                offending_event_id = match.group(1).strip()
            metadata = dict(request.metadata)
            if offending_event_id:
                metadata["offending_event_id"] = offending_event_id
            retry_prompt = request.user_prompt
            retry_prompt += (
                f"\n\n上一次拆分输出未通过结构化校验。这是第 {attempt} 次尝试。"
                f" 失败原因：{normalized_error}。"
            )
            retry_prompt += (
                " 这次任务不是重写整章，而是只把当前粗事件拆开。"
                " replacement events 至少输出 2 条，通常 2-3 条即可。"
                " 每条 replacement event 只保留更窄的一拍推进，不要再把问句、回答、动作结果或关系落点重新合并回同一条。"
                " 不要输出 event_id，不要改写相邻 event，不要解释，不要输出 Markdown 代码块。"
            )
            return PromptRequest(
                system_prompt=request.system_prompt,
                user_prompt=retry_prompt,
                metadata=metadata,
            )
        if task_name == "video-scene-chunk-repair" and "chunk" in normalized_error and "动作容量过载" in normalized_error:
            offending_chunk_id = ""
            required_segment_count = 0
            chunk_match = re.search(r"chunk\s+(\S+)\s+动作容量过载", normalized_error)
            if chunk_match is not None:
                offending_chunk_id = str(chunk_match.group(1) or "").strip()
            required_match = re.search(r"expected_segment_count 至少应为\s+(\d+)", normalized_error)
            if required_match is not None:
                required_segment_count = int(required_match.group(1))
            metadata = dict(request.metadata)
            if offending_chunk_id:
                metadata["offending_chunk_id"] = offending_chunk_id
            if required_segment_count > 0:
                metadata["required_segment_count"] = required_segment_count
            retry_prompt = request.user_prompt
            retry_prompt += (
                f"\n\n上一次修复输出未通过结构化校验。这是第 {attempt} 次尝试。"
                f" 失败原因：{normalized_error}。"
            )
            if offending_chunk_id:
                retry_prompt += (
                    f" 本次只优先修 `{offending_chunk_id}`，不要回头大改前面已经合理的 chunk。"
                )
            if required_segment_count > 0:
                retry_prompt += (
                    f" 当前失败项如果继续保留为单个 chunk，`expected_segment_count` 至少要改成 {required_segment_count}；"
                    "如果你不想提高它，就必须把当前 chunk 拆成两个连续 chunk。"
                )
            retry_prompt += (
                " 不要再把 4 个及以上推进点继续塞在同一个 chunk。"
                " `must_cover` 与 `transition_goal` 只保留当前 chunk 自己负责的那一小段推进。"
                " 不要解释，不要输出 Markdown 代码块，不要漏字段。"
            )
            return PromptRequest(
                system_prompt=request.system_prompt,
                user_prompt=retry_prompt,
                metadata=metadata,
            )
        if task_name == "video-scene-segment-timeline-repair" and "timed_beats" in normalized_error:
            offending_segment_id = ""
            segment_match = re.search(
                r"segment\s+(?P<segment_id>\S+)\s+的\s+timed_beats",
                normalized_error,
            )
            if segment_match is not None:
                offending_segment_id = str(segment_match.group("segment_id") or "").strip()
            metadata = dict(request.metadata)
            if offending_segment_id:
                metadata["offending_segment_id"] = offending_segment_id
            retry_prompt = request.user_prompt
            retry_prompt += (
                f"\n\n上一次修复输出未通过结构化校验。这是第 {attempt} 次尝试。"
                f" 失败原因：{normalized_error}。"
            )
            if offending_segment_id:
                retry_prompt += (
                    f" 本次只优先修 `{offending_segment_id}` 的 timed_beats，"
                    "不要回头大改已经合理的其他 segment。"
                )
            retry_prompt += (
                " 末尾 beat 必须补到接近该段 duration_seconds 结束，"
                "明确写出尾部可拍到的反应、停顿、走位收束或镜头停点。"
                " 如果只是尾部少了 1-3 秒，不要新造剧情结果，优先在现有结果上补完整收束。"
                " 不要解释，不要输出 Markdown 代码块，不要漏字段。"
            )
            return PromptRequest(
                system_prompt=request.system_prompt,
                user_prompt=retry_prompt,
                metadata=metadata,
            )
        if task_name == "video-scene-segment-action-repair" and "动作容量过载" in normalized_error:
            offending_segment_id = ""
            required_segment_count = 0
            segment_match = re.search(
                r"segment\s+(?P<segment_id>\S+)\s+的\s+动作容量过载",
                normalized_error,
            )
            if segment_match is not None:
                offending_segment_id = str(segment_match.group("segment_id") or "").strip()
            required_match = re.search(
                r"当前 chunk 必须至少拆成\s+(?P<count>\d+)\s+个 segment",
                normalized_error,
            )
            if required_match is not None:
                required_segment_count = int(required_match.group("count"))
            metadata = dict(request.metadata)
            if offending_segment_id:
                metadata["offending_segment_id"] = offending_segment_id
            if required_segment_count > 0:
                metadata["required_segment_count"] = required_segment_count
            retry_prompt = request.user_prompt
            retry_prompt += (
                f"\n\n上一次修复输出未通过结构化校验。这是第 {attempt} 次尝试。"
                f" 失败原因：{normalized_error}。"
            )
            if offending_segment_id:
                retry_prompt += (
                    f" 本次只优先修 `{offending_segment_id}`，"
                    "不要回头大改已经合理的其他 segment。"
                )
            if required_segment_count > 0:
                retry_prompt += (
                    f" 当前 chunk 至少要拆成 {required_segment_count} 个 segment；"
                    "不要继续把多个动作结果硬塞回单段。"
                )
            retry_prompt += (
                " 你必须按动作结果、对白轮次、入画变化或关系推进点把过载片段拆开，"
                "让每一段只承担更窄的一拍推进。"
                " 不要解释，不要输出 Markdown 代码块，不要漏字段。"
            )
            return PromptRequest(
                system_prompt=request.system_prompt,
                user_prompt=retry_prompt,
                metadata=metadata,
            )
        if task_name == "video-scene-segment-focus-repair" and "多人同帧时仍要求单人特写" in normalized_error:
            parsed = self._parse_scene_segment_focus_conflict_failure(normalized_error)
            offending_segment_id = str(parsed.get("segment_id", "") or "").strip()
            field_name = str(parsed.get("field_name", "") or "").strip()
            frame_label = str(parsed.get("frame_label", "") or "").strip()
            frame_characters = list(parsed.get("frame_characters", []) or [])
            frame_names = "、".join(frame_characters) or "未知角色"
            focus_name = frame_characters[0] if frame_characters else "主角"
            metadata = dict(request.metadata)
            if offending_segment_id:
                metadata["offending_segment_id"] = offending_segment_id
            if field_name:
                metadata["field_name"] = field_name
            if frame_label:
                metadata["frame_label"] = frame_label
            retry_prompt = request.user_prompt
            retry_prompt += (
                f"\n\n上一次修复输出未通过结构化校验。这是第 {attempt} 次尝试。"
                f" 失败原因：{normalized_error}。"
            )
            if offending_segment_id:
                retry_prompt += (
                    f" 本次只优先修 `{offending_segment_id}`，"
                    "不要回头大改已经合理的其他 segment。"
                )
            retry_prompt += (
                f" 当前冲突画面是 `{frame_label or 'unknown_frame'}`，角色组是 `{frame_names}`。"
                f" 只要当前画面仍保持 `{frame_names}` 同框，就必须把 `shot_state.framing` 和 `shot_state.camera_motion` 一起改成共享镜头语言，"
                f"例如“轻微前推，保持 {frame_names} 同框，只通过站位和表情差异突出 {focus_name} 情绪变化”。"
                " 不要再保留任何“单人近景”“侧脸特写”“聚焦某人脸部”这类单人特写话术。"
            )
            retry_prompt += (
                f" 不要把 `{frame_label}` 画面约束偷偷改成单人特写来规避校验。"
                "多人同框时应改共享镜头语言，而不是改角色集合。"
            )
            retry_prompt += " 不要解释，不要输出 Markdown 代码块，不要漏字段。"
            return PromptRequest(
                system_prompt=request.system_prompt,
                user_prompt=retry_prompt,
                metadata=metadata,
            )
        return self._build_structured_retry_request(
            request=request,
            schema=schema,
            attempt=attempt,
            last_error=last_error,
            retry_prefix="上一次修复输出未通过结构化校验。",
            retry_suffix="不要解释，不要输出 Markdown 代码块，不要缺字段，不要改目标 segment_id。",
        )

    def _build_retry_request(
        self,
        *,
        request: PromptRequest,
        schema: type[StructuredModelT],
        attempt: int,
        last_error: Exception | None,
    ) -> PromptRequest:
        return self._build_structured_retry_request(
            request=request,
            schema=schema,
            attempt=attempt,
            last_error=last_error,
            retry_prefix="上一次输出未通过结构化校验。",
            retry_suffix=(
                "不要解释，不要输出 Markdown 代码块，不要遗漏字段，"
                "不要把分析备注写成正式分镜内容。"
            ),
        )

    def _build_structured_retry_request(
        self,
        *,
        request: PromptRequest,
        schema: type[StructuredModelT],
        attempt: int,
        last_error: Exception | None,
        retry_prefix: str,
        retry_suffix: str,
    ) -> PromptRequest:
        if attempt <= 1:
            return request

        normalized_error = " ".join(str(last_error or "").split()).strip()
        retry_note = f"\n\n{retry_prefix}这是第 {attempt} 次尝试。"
        if normalized_error:
            retry_note += f" 失败原因：{normalized_error}。"
        if "finish_reason='length'" in normalized_error or 'finish_reason="length"' in normalized_error:
            retry_note += (
                " 这次失败说明上一次输出过长被截断。"
                "请显著压缩输出：scene_bible 只保留短句和少量列表项，"
                "segment 不要重复父级 scene 的 scene_title/scene_summary/scene_anchor/scene_bible，"
                "title、summary、narration、shot_state、continuity_link 字段都尽量只写 1 句短描述。"
                "timed_beats 通常控制在 1-3 条，不要用长段散文。"
            )
        if "当前对白/字幕至少需要" in normalized_error:
            retry_note += (
                " 这次失败说明对白、旁白或字幕仍然过长。"
                "本次必须显著压缩 narration、dialogue_lines、subtitle_lines 的总字数，"
                "确保 required_duration 不超过 duration_seconds。"
                "如果 12 秒内说不完，就删减文本，不要保留原长对白。"
            )
        if isinstance(last_error, SegmentSpeechSplitRequiredError):
            retry_note += (
                f" 这次失败说明某个 segment 的对白预算约 {last_error.required_duration_seconds} 秒，"
                f"已经超过单段 {last_error.max_duration_seconds} 秒上限。"
                f" 本次必须把当前 chunk 至少拆成 {last_error.required_segment_count} 个 segment，"
                "按对白轮次、句意边界或动作结果落点重排，"
                "不要再尝试把整段对白压成单段。"
            )
        if isinstance(last_error, SegmentActionSplitRequiredError):
            retry_note += (
                f" 这次失败说明某个 segment 的动作容量约有 {last_error.action_node_count} 个推进点，"
                f"但当前 {last_error.current_duration_seconds} 秒片段最多只允许 {last_error.max_action_nodes} 个。"
                f" 本次必须把当前 chunk 至少拆成 {last_error.required_segment_count} 个 segment，"
                "按动作结果、对白轮次、入画变化或关系推进点拆开，"
                "不要把“等待 -> 会面 -> 开口”或“试探 -> 告白 -> 回应”继续硬塞在同一段里。"
            )
        if "动作容量过载" in normalized_error and "expected_segment_count 至少应为" in normalized_error:
            retry_note += (
                " 这次失败说明某个 chunk 自己就塞了太多推进点。"
                "请在 chunk 层先拆开事件，或把 `expected_segment_count` 提高到足够覆盖这些推进点。"
                "如果 `must_cover + transition_goal` 已经包含多轮动作结果，不要还写成 1 个 segment。"
            )
        if (
            "缺少 timed_beats" in normalized_error
            or "timed_beats 不能为空" in normalized_error
            or (
                "timed_beats" in normalized_error
                and ("Field required" in normalized_error or "missing" in normalized_error.lower())
            )
        ):
            retry_note += (
                " 这次失败说明有片段漏掉了必填的 timed_beats。"
                "本次输出时，每个 segment 都必须显式带非空 timed_beats 列表，"
                "即使是纯动作段也不能省略。"
                "每条 timed_beats 都要写成“0-2秒：发生了什么”的具体秒数格式，"
                "并覆盖该段的开场、推进和收束。"
            )
        if "尾部约" in normalized_error and "缺少明确动作或收束节拍" in normalized_error:
            retry_note += (
                " 这次失败说明 timed_beats 虽然存在，但最后几秒没有覆盖完整时长。"
                "本次必须把最后一条 beat 或新增一条收束 beat 补到接近 duration_seconds 结束，"
                "明确写出尾部的反应、停顿、走位收束或镜头停点。"
                "不要再让片段在最后 1-3 秒处于没有合同约束的空白状态。"
            )
        if "多人同帧时仍要求单人特写" in normalized_error or "画面里重复出现" in normalized_error:
            retry_note += (
                " 这次失败说明人物构图自相矛盾。"
                "如果当前片段是双人或多人同框，就不要再写“某角色侧脸特写 / 大特写 / 单人近景”。"
                "`shot_state.framing` 和 `shot_state.camera_motion` 是整个 segment 共享的镜头约束，"
                "多人同框时应改成关系镜头或共享镜头语言，避免把同一角色重复生成。"
                "例如不要写“推向苏晴侧脸特写”，应改成“轻微前推，保持两人同框并捕捉苏晴表情变化”。"
            )
            multi_focus_match = re.search(
                r"segment\s+(?P<segment_id>\S+)\s+的\s+(?P<field_name>[^\s]+)\s+在\s+"
                r"(?P<frame_label>segment)\s*"
                r"\((?P<frame_names>[^)]+)\)\s*多人同帧时仍要求单人特写",
                normalized_error,
            )
            if multi_focus_match:
                field_name = str(multi_focus_match.group("field_name") or "").strip()
                frame_label = str(multi_focus_match.group("frame_label") or "").strip()
                frame_names = str(multi_focus_match.group("frame_names") or "").strip()
                if field_name and frame_label and frame_names:
                    focus_name = frame_names.split("、", 1)[0].strip() or frame_names
                    retry_note += (
                        f" 本次直接按这条修：当前报错的是 `{field_name}` 在 `{frame_label}`，"
                        f"该帧角色是 `{frame_names}`。"
                        f"如果 `{frame_label}` 仍要求 `{frame_names}` 同框，"
                        f"就把 `{field_name}` 改写成共享镜头语言，"
                        f"例如“轻微前推，保持 {frame_names} 同框，只通过站位和表情差异突出 {focus_name} 情绪变化”；"
                        f"不要再写“推向 {focus_name} 侧脸特写”“聚焦到 {focus_name} 脸部”这类单人特写句。"
                    )
        if "缺少 continuity_link.opening_match" in normalized_error or "opening_match 过于空泛" in normalized_error:
            retry_note += (
                " 这次失败说明 opening_match 不合格。"
                "无论是 start 还是 continue，opening_match 都必须写成可拍到的开场状态，"
                "不要留空，也不要写“承接上一段继续”“场景开始”这类空话。"
            )
        if "首段 opening_match 没有明确承接上一 chunk 尾部状态" in normalized_error:
            retry_note += (
                " 这次失败说明跨 chunk 首段没有把上一 chunk 的尾部状态真正复现到开场画面里。"
                "请直接复用 `上一 chunk 退出状态 JSON` 里的 `visible_tail_state`、"
                "`opening_match_seed` 和 `carry_over_elements`，"
                "把当前首段的 continuity_link.opening_match 改写成可拍到的承接句。"
                "优先写清角色仍保持的站位、朝向、道具和动作停点，"
                "例如“承接上一 chunk 尾部，陈默仍停在长椅旁微微回头，保持刚听见脚步声后停住的姿态”。"
                "不要只写“继续推进到会面”“承接上一段尾部”这类抽象总结。"
            )
        if (
            "scene_transition_contract" in normalized_error
            or "首个 chunk 没有消费 scene_transition_contract" in normalized_error
            or "首段 opening_match 没有承接 scene_transition_contract" in normalized_error
            or "首段 timed_beats 没有消费 scene_transition_contract" in normalized_error
        ):
            retry_note += (
                " 这次失败说明跨 scene 过渡合同没有被真正消费。"
                "如果当前不是首个 scene，就必须先用 `scene_transition_contract` 建立上一场尾部到当前场开头的桥。"
                "本次至少要做到四点："
                "第一，scene 级合同里的 `previous_scene_id / transition_mode / next_scene_entry_match` 不能缺；"
                "第二，`next_scene_entry_match` 必须写成当前 scene 第一秒可拍画面，包含当前地点/背景锚点 + 角色站位/朝向/动作停点，不能只写抽象情绪或只复述上一场尾部；"
                "第三，首个 chunk 必须把 `bridge_action` 和 `visual_bridge` 写进自己的开场推进；"
                "第四，首个 segment 的 `opening_match` 和前 1-2 条 `timed_beats` 必须先承接上一场尾部，再 reveal 当前场环境。"
                "不要把新 scene 直接写成毫无来由的重新开场。"
            )
        if (
            "covered_event_ids" in normalized_error
            or "关键事件覆盖" in normalized_error
            or "章节关键事件" in normalized_error
            or "must-cover event" in normalized_error
            or "source_evidence 无法在当前章节正文中定位" in normalized_error
        ):
            retry_note += (
                " 这次失败说明当前章节的 scene 没有完整覆盖关键事件。"
                "本次必须严格对齐关键事件列表：每个 scene 都要填写 covered_event_ids，"
                "所有 covered_event_ids 拼接后必须与关键事件顺序完全一致，"
                "尤其不能漏掉章节后半段的关系落点、动作结果或结尾决定。"
            )
        if "关键事件" in normalized_error and "推进点" in normalized_error and "过于粗" in normalized_error:
            retry_note += (
                " 这次失败说明 chapter event planner 把多个推进阶段合并成了同一个关键事件。"
                "本次必须把粗事件拆成更细的相邻 event："
                "普通 event 最多只保留 1-2 个紧密绑定的推进点；如果当前章节已经拆成多个 event，章节首尾 event 最多允许 3 个。"
                "如果一句里已经同时出现“等待 -> 会面 -> 开口”或“试探 -> 告白 -> 回应”，"
                "就必须改写成多个连续 event_id，而不是继续塞进同一个 summary。"
                "背景介绍、关系说明、回忆补叙如果只是解释上下文，也不要单独建成 must-cover event。"
                "中间 event 尤其不能把一轮问句、一次回答和一个动作结果同时塞进去。"
                "`source_evidence` 也只保留当前 event 对应的 1-2 个相邻正文短句，"
                "不要把后续 event 的证据一起拼进来。"
            )
        if "重复表达同一事件" in normalized_error or "adjacent_segment_duplicate" in normalized_error:
            retry_note += (
                " 这次失败说明你把同一动作链拆得过碎。"
                "本次应主动合并近义相邻 segment，优先减少 segment 数，"
                "不要为了凑满 expected_segment_count 而重复同一事件。"
            )
        retry_note += f" 请严格按 {schema.__name__} 返回。{retry_suffix}"
        metadata = dict(request.metadata)
        metadata["structured_retry_attempt"] = attempt
        return PromptRequest(
            system_prompt=request.system_prompt,
            user_prompt=request.user_prompt + retry_note,
            metadata=metadata,
        )


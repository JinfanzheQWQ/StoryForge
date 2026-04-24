from __future__ import annotations


class VideoStructuredGenerationError(RuntimeError):
    def __init__(
        self,
        *,
        task: str,
        schema_name: str,
        attempts: int,
        cause: Exception,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.task = task
        self.schema_name = schema_name
        self.attempts = attempts
        self.cause = cause
        self.metadata = metadata or {}
        self.chapter_number = int(self.metadata.get("chapter_number", 0) or 0)
        self.scene_id = str(self.metadata.get("scene_id", "") or "")
        self.chunk_id = str(self.metadata.get("chunk_id", "") or "")
        self.chunk_order_index = int(self.metadata.get("chunk_order_index", 0) or 0)
        location_suffix = ""
        if self.chapter_number:
            location_suffix += f" chapter={self.chapter_number}"
        if self.scene_id:
            location_suffix += f" scene_id={self.scene_id}"
        if self.chunk_id:
            location_suffix += f" chunk_id={self.chunk_id}"
        elif self.chunk_order_index:
            location_suffix += f" chunk_order_index={self.chunk_order_index}"
        super().__init__(
            f"Structured generation failed for task={task} schema={schema_name} "
            f"after {attempts} attempts{location_suffix}: {cause}"
        )


class SegmentSpeechSplitRequiredError(ValueError):
    def __init__(
        self,
        *,
        segment_id: str,
        required_duration_seconds: int,
        current_duration_seconds: int,
        max_duration_seconds: int,
        required_segment_count: int,
    ) -> None:
        self.segment_id = segment_id
        self.required_duration_seconds = required_duration_seconds
        self.current_duration_seconds = current_duration_seconds
        self.max_duration_seconds = max_duration_seconds
        self.required_segment_count = required_segment_count
        super().__init__(
            f"segment {segment_id} 的对白/字幕至少需要 {required_duration_seconds} 秒，"
            f"但单段上限只有 {max_duration_seconds} 秒，"
            f"当前 chunk 必须至少拆成 {required_segment_count} 个 segment。"
        )


class SegmentActionSplitRequiredError(ValueError):
    def __init__(
        self,
        *,
        segment_id: str,
        action_node_count: int,
        current_duration_seconds: int,
        max_action_nodes: int,
        required_segment_count: int,
    ) -> None:
        self.segment_id = segment_id
        self.action_node_count = action_node_count
        self.current_duration_seconds = current_duration_seconds
        self.max_action_nodes = max_action_nodes
        self.required_segment_count = required_segment_count
        super().__init__(
            f"segment {segment_id} 的动作容量过载："
            f"当前约有 {action_node_count} 个推进点，"
            f"但 {current_duration_seconds} 秒片段最多只允许 {max_action_nodes} 个。"
            f"当前 chunk 必须至少拆成 {required_segment_count} 个 segment。"
        )

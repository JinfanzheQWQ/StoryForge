from __future__ import annotations


class NovelStructuredGenerationError(RuntimeError):
    def __init__(
        self,
        *,
        task: str,
        schema_name: str,
        attempts: int,
        cause: Exception,
    ) -> None:
        self.task = task
        self.schema_name = schema_name
        self.attempts = attempts
        self.cause = cause
        super().__init__(
            f"Structured generation failed for task={task} schema={schema_name} "
            f"after {attempts} attempts: {cause}"
        )

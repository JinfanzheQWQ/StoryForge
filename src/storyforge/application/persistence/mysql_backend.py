from __future__ import annotations

from typing import Any

from storyforge.core.config import DatabaseConfig


class MySQLBackend:
    def __init__(self, config: DatabaseConfig) -> None:
        try:
            import pymysql
        except ImportError as exc:  # pragma: no cover - optional until DB is enabled
            raise RuntimeError(
                "Database backend requires PyMySQL. Run `uv sync` to install dependencies."
            ) from exc

        self._pymysql = pymysql
        self._config = config
        if self._config.auto_create_schema:
            self.ensure_schema()

    def connect(self):
        return self._connect(use_database=True)

    def ensure_schema(self) -> None:
        database_name = self._quote_identifier(self._config.database)
        charset = self._config.charset

        bootstrap_connection = self._connect(use_database=False)
        try:
            with bootstrap_connection.cursor() as cursor:
                cursor.execute(
                    f"CREATE DATABASE IF NOT EXISTS {database_name} "
                    f"CHARACTER SET {charset} COLLATE {charset}_unicode_ci"
                )
        finally:
            bootstrap_connection.close()

        schema_connection = self._connect(use_database=True)
        try:
            with schema_connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS projects (
                        project_id VARCHAR(64) PRIMARY KEY,
                        title_hint VARCHAR(255) NOT NULL,
                        brief_json LONGTEXT NOT NULL,
                        created_at VARCHAR(40) NOT NULL,
                        updated_at VARCHAR(40) NOT NULL,
                        task_ids_json LONGTEXT NOT NULL,
                        latest_task_id VARCHAR(64) NULL,
                        story_title VARCHAR(255) NULL,
                        last_output_dir TEXT NULL,
                        INDEX idx_projects_updated_at (updated_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tasks (
                        task_id VARCHAR(64) PRIMARY KEY,
                        project_id VARCHAR(64) NOT NULL,
                        task_type VARCHAR(120) NOT NULL,
                        status VARCHAR(20) NOT NULL,
                        payload_json LONGTEXT NOT NULL,
                        created_at VARCHAR(40) NOT NULL,
                        started_at VARCHAR(40) NULL,
                        finished_at VARCHAR(40) NULL,
                        result_json LONGTEXT NULL,
                        error_text TEXT NULL,
                        INDEX idx_tasks_project_created (project_id, created_at),
                        INDEX idx_tasks_status_created (status, created_at),
                        CONSTRAINT fk_tasks_project
                            FOREIGN KEY (project_id) REFERENCES projects(project_id)
                            ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
        finally:
            schema_connection.close()

    def _connect(self, use_database: bool):
        params: dict[str, Any] = {
            "host": self._config.host,
            "port": self._config.port,
            "user": self._config.user,
            "password": self._config.resolved_password(),
            "charset": self._config.charset,
            "autocommit": True,
            "connect_timeout": self._config.connect_timeout_seconds,
            "cursorclass": self._pymysql.cursors.DictCursor,
        }
        if use_database:
            params["database"] = self._config.database
        try:
            return self._pymysql.connect(**params)
        except Exception as exc:
            database_label = self._config.database if use_database else "<server>"
            raise RuntimeError(
                "MySQL connection failed. "
                f"host={self._config.host} port={self._config.port} "
                f"user={self._config.user} database={database_label}. "
                "Check whether MySQL is running and whether the configured password is correct."
            ) from exc

    @staticmethod
    def _quote_identifier(value: str) -> str:
        return f"`{value.replace('`', '``')}`"

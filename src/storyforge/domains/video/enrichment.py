from __future__ import annotations

from storyforge.domains.novel.contracts import NovelPackage
from storyforge.domains.video.schemas import ChapterSceneSchema


class VideoEnrichmentMixin:
    def _build_local_sound_effects(
        self,
        scene_bible,
        timed_beats: list[str],
    ) -> list[str]:
        effects: list[str] = []
        weather = self._scene_bible_value(scene_bible, "weather").strip()
        if weather:
            effects.append(f"{weather}环境声")
        fixed_props = self._scene_bible_environment_fixed_props(scene_bible)
        if fixed_props:
            effects.append(f"{fixed_props[0]}相关细节声")
        beat_text = " ".join(timed_beats)
        if any(keyword in beat_text for keyword in ("走", "跑", "靠近", "停下", "转身", "拥抱")):
            effects.append("脚步与衣料摩擦声")
        sanitized_effects = self._sanitize_segment_sound_effects(
            effects,
            scene_bible=scene_bible,
        )
        if not sanitized_effects:
            sanitized_effects = ["环境底噪"]
        return sanitized_effects[:3]

    def _build_local_music_direction(
        self,
        *,
        novel_package: NovelPackage,
        scene: ChapterSceneSchema,
        segment_summary: str,
    ) -> str:
        return (
            f"延续 {novel_package.brief.tone} 的整体气质，"
            f"围绕 {scene.title} / {segment_summary} 的情绪推进铺陈，不要压过对白和环境音。"
        )

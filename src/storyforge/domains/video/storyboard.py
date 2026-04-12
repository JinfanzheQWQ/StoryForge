from __future__ import annotations

from storyforge.domains.novel.contracts import NovelPackage
from storyforge.domains.video.contracts import Shot, Storyboard


def build_storyboard(
    novel_package: NovelPackage,
    scene_duration_seconds: int,
    agent_notes: str = "",
) -> Storyboard:
    shots: list[Shot] = []

    for chapter in novel_package.outline.chapters:
        for scene_index, beat in enumerate(chapter.beats, start=1):
            shot_id = f"ch{chapter.number:02d}_s{scene_index:02d}"
            shots.append(
                Shot(
                    shot_id=shot_id,
                    chapter_number=chapter.number,
                    scene_title=f"{chapter.title} / 场景 {scene_index}",
                    duration_seconds=scene_duration_seconds,
                    visual_prompt=(
                        f"{novel_package.outline.title}，{beat}，风格关键词："
                        f"{'、'.join(novel_package.brief.style_keywords or novel_package.outline.visual_motifs)}"
                    ),
                    narration=(
                        f"第 {chapter.number} 章，{chapter.summary}"
                        f"这一场景聚焦于：{beat}"
                    ),
                    camera_move="slow push-in",
                    music_cue=f"延续 {novel_package.brief.tone} 的氛围音乐，并在结尾制造悬念。",
                )
            )

    voiceover_script = "\n".join(shot.narration for shot in shots)
    return Storyboard(
        title=novel_package.outline.title,
        style_guide=novel_package.outline.visual_motifs,
        shots=shots,
        voiceover_script=voiceover_script,
        agent_notes=agent_notes,
    )

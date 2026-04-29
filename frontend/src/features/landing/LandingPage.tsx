import { type FormEvent, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight } from "lucide-react";

const workflow = ["小说正文", "场景结构", "角色定妆", "场景母图", "分段视频", "合并交付"];

const heroLines = ["把故事拍成画面", "从一句话到一支短片", "让小说进入镜头", "把脑海里的画面做出来", "让灵感自己开机"];

const heroPromptExample = "傍晚的校园花园里，一个内向男生在银杏树下误以为自己叫住了喜欢的女生，最后鼓起勇气表白。";

export function LandingPage() {
  const [idea, setIdea] = useState(heroPromptExample);
  const [heroLineIndex, setHeroLineIndex] = useState(0);
  const navigate = useNavigate();

  useEffect(() => {
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (reducedMotion.matches) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      setHeroLineIndex((current) => (current + 1) % heroLines.length);
    }, 6800);
    return () => window.clearInterval(timer);
  }, []);

  function submitIdea(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedIdea = idea.trim();
    if (!trimmedIdea) {
      return;
    }
    navigate(`/console/new?idea=${encodeURIComponent(trimmedIdea)}`);
  }

  return (
    <section className="landing-page video-led">
      <section className="landing-hero" aria-labelledby="landing-title">
        <div className="hero-video-layer" aria-hidden="true">
          <video className="hero-video" autoPlay muted loop playsInline poster="/media/storyforge-hero-poster.png">
            <source src="/media/storyforge-hero.mp4" type="video/mp4" />
          </video>
          <div className="hero-video-fallback" />
          <div className="hero-scrim" />
        </div>

        <div className="hero-statement">
          <h1 id="landing-title">StoryForge</h1>
          <p>{heroLines[heroLineIndex]}</p>
          <form className="hero-composer" id="create" onSubmit={submitIdea} aria-label="输入创意开始创作">
            <textarea aria-label="故事创意" value={idea} onChange={(event) => setIdea(event.target.value)} required />
            <div className="hero-composer-footer">
              <button className="hero-primary" type="submit">
                开始创作
                <ArrowRight size={18} aria-hidden="true" />
              </button>
            </div>
          </form>
        </div>
      </section>

      <section className="landing-process" id="workflow" aria-label="StoryForge 生产流程">
        <div className="process-copy">
          <p className="hero-kicker">Production Flow</p>
          <h2>从一句创意，到一条可审片的视频生产线。</h2>
          <p>进入创作器后，StoryForge 会按固定链路生成小说、结构、角色、场景、分段视频和最终成片。</p>
        </div>
        <ol className="process-track">
          {workflow.map((item, index) => (
            <li key={item}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <strong>{item}</strong>
            </li>
          ))}
        </ol>
      </section>

      <section className="landing-final">
        <p>把故事交给生产线，把审片权留给创作者。</p>
        <div className="final-actions">
          <Link className="hero-primary" to="/console/new">
            创建视频项目
            <ArrowRight size={18} aria-hidden="true" />
          </Link>
          <Link className="hero-secondary light" to="/console">
            进入项目库
          </Link>
        </div>
      </section>
    </section>
  );
}

import { FormEvent, useState } from "react";
import { LoaderCircle, SendHorizontal } from "lucide-react";

interface AgentComposerProps {
  canConfirm: boolean;
  disabled?: boolean;
  isBusy?: boolean;
  isCreatingSession?: boolean;
  onConfirm: () => void;
  onSubmit: (content: string) => void;
  statusHint: string;
}

export function AgentComposer({
  canConfirm,
  disabled = false,
  isBusy = false,
  isCreatingSession = false,
  onConfirm,
  onSubmit,
  statusHint
}: AgentComposerProps) {
  const [content, setContent] = useState("");
  const blocked = disabled || isBusy || isCreatingSession;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = content.trim();
    if (!value || blocked) return;
    onSubmit(value);
    setContent("");
  }

  return (
    <form className="agent-composer" onSubmit={submit}>
      <label>
        <span>{statusHint}</span>
        <textarea
          disabled={blocked}
          placeholder="描述你想生成的视频：题材、人物、场景、情绪、风格、时长倾向..."
          rows={3}
          value={content}
          onChange={(event) => setContent(event.target.value)}
        />
      </label>
      <div className="agent-composer-actions">
        {canConfirm ? (
          <button className="agent-confirm-button" disabled={isBusy} type="button" onClick={onConfirm}>
            {isBusy ? <LoaderCircle className="spin" size={15} aria-hidden="true" /> : null}
            确认开始
          </button>
        ) : null}
        <button className="agent-send-button" disabled={!content.trim() || blocked} type="submit">
          {isBusy || isCreatingSession ? <LoaderCircle className="spin" size={15} aria-hidden="true" /> : <SendHorizontal size={15} />}
          发送
        </button>
      </div>
    </form>
  );
}

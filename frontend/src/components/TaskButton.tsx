import type { ButtonHTMLAttributes, ReactNode } from "react";
import { LoaderCircle } from "lucide-react";

interface TaskButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  loading?: boolean;
  children: ReactNode;
}

export function TaskButton({ loading = false, children, disabled, className = "", ...props }: TaskButtonProps) {
  return (
    <button className={["task-button", className].filter(Boolean).join(" ")} disabled={disabled || loading} {...props}>
      {loading ? <LoaderCircle className="spin" size={16} aria-hidden="true" /> : null}
      <span>{children}</span>
    </button>
  );
}

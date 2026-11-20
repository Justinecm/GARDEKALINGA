// Bottom sheet on phones, centred dialog on wide screens. Built on <dialog> for a
// real focus trap, Esc to close and an inert page behind it.
import { useEffect, useId, useRef, type ReactNode } from "react";
import { useI18n } from "../i18n/I18n";
import Icon from "./Icon";
import s from "./Sheet.module.css";

interface Props {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  actions?: ReactNode;
  labelledBy?: string;
}

export default function Sheet({ open, title, onClose, children, actions }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  const { t } = useI18n();

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className={s.dialog}
      aria-labelledby={id}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
    >
      {open && (
        <div className={s.panel}>
          <div className={s.grip} aria-hidden="true" />
          <div className={s.head}>
            <h2 id={id} className={s.title}>
              {title}
            </h2>
            <button type="button" className={`btn btn-link ${s.close}`} onClick={onClose} aria-label={t("close")}>
              <Icon name="x" />
            </button>
          </div>
          {children}
          {actions && <div className={s.actions}>{actions}</div>}
        </div>
      )}
    </dialog>
  );
}

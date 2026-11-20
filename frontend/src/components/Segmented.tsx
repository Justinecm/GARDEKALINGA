// Radio-group styled as a segmented control (keyboard: arrows move, like native radios).
import { useId } from "react";

interface Props<T extends string> {
  label: string;
  value: T;
  options: { value: T; label: string; disabled?: boolean }[];
  onChange: (v: T) => void;
  hideLabel?: boolean;
}

export default function Segmented<T extends string>({ label, value, options, onChange, hideLabel }: Props<T>) {
  const name = useId();
  return (
    <fieldset className="segmented">
      <legend className={hideLabel ? "visually-hidden" : "label"}>{label}</legend>
      <div className="segmented-row">
        {options.map((o) => (
          <label key={o.value} className={`segmented-opt${o.value === value ? " is-on" : ""}${o.disabled ? " is-disabled" : ""}`}>
            <input type="radio" name={name} value={o.value} checked={o.value === value} disabled={o.disabled} onChange={() => onChange(o.value)} />
            <span>{o.label}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

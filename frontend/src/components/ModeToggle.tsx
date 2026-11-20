import { BookOpenIcon, SparklesIcon } from "lucide-react";
import type { Mode } from "../chat/types";
import { Segmented } from "./ui/segmented";

interface Props {
  mode: Mode;
  onChange: (mode: Mode) => void;
}

export default function ModeToggle({ mode, onChange }: Props) {
  return (
    <Segmented
      label="Explanation mode"
      size="sm"
      value={mode}
      onChange={onChange}
      options={[
        {
          value: "simple",
          label: (
            <>
              <SparklesIcon className="size-3.5" aria-hidden="true" />
              Simple
            </>
          ),
          name: "Simple",
          hint: "Short answers in plain words",
        },
        {
          value: "detailed",
          label: (
            <>
              <BookOpenIcon className="size-3.5" aria-hidden="true" />
              Detailed
            </>
          ),
          name: "Detailed",
          hint: "Figures, formulas and caveats",
        },
      ]}
    />
  );
}

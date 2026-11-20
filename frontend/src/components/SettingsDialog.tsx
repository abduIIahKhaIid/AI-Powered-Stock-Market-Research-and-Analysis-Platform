/** Chat settings (like Chainlit's settings panel): theme, chain of thought and motion. */
import { MonitorIcon, MoonIcon, SunIcon } from "lucide-react";
import { useId } from "react";
import { type ChainOfThought, type Theme, useSettings } from "../settings/context";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "./ui/dialog";
import { Segmented } from "./ui/segmented";
import { Switch } from "./ui/switch";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const COT_HELP: Record<ChainOfThought, string> = {
  full: "Show the model's reasoning and every data step in the Thinking panel.",
  tool_call: "Show only the data steps (tool calls), not the reasoning text.",
  hidden: "Show only a short status line while the assistant works.",
};

function Row({
  title,
  help,
  children,
}: {
  title: string;
  help: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2 py-4 sm:flex-row sm:items-center sm:justify-between sm:gap-6">
      <div>
        <p className="text-sm font-medium">{title}</p>
        <p className="text-xs text-muted-foreground">{help}</p>
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

export default function SettingsDialog({ open, onOpenChange }: Props) {
  const settings = useSettings();
  const motionId = useId();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent closeLabel="Close settings" className="w-[min(92vw,34rem)]">
        <div className="border-b border-border px-5 py-4 pr-12">
          <DialogTitle className="text-base font-semibold">Settings</DialogTitle>
          <DialogDescription className="text-xs text-muted-foreground">
            Saved in this browser.
          </DialogDescription>
        </div>
        <div className="divide-y divide-border px-5">
          <Row title="Theme" help="Light, dark, or follow your system.">
            <Segmented<Theme>
              label="Theme"
              size="sm"
              value={settings.theme}
              onChange={(theme) => settings.update({ theme })}
              options={[
                { value: "light", name: "Light", label: <SunIcon className="size-3.5" /> },
                { value: "dark", name: "Dark", label: <MoonIcon className="size-3.5" /> },
                { value: "system", name: "System", label: <MonitorIcon className="size-3.5" /> },
              ]}
            />
          </Row>
          <Row title="Chain of thought" help={COT_HELP[settings.chainOfThought]}>
            <Segmented<ChainOfThought>
              label="Chain of thought"
              size="sm"
              value={settings.chainOfThought}
              onChange={(chainOfThought) => settings.update({ chainOfThought })}
              options={[
                { value: "full", label: "Full" },
                { value: "tool_call", label: "Tools" },
                { value: "hidden", label: "Hidden" },
              ]}
            />
          </Row>
          <Row
            title="Animations"
            help="Draw charts in and animate panels. Turned off when your system asks for less motion."
          >
            <span className="flex items-center gap-2">
              <label htmlFor={motionId} className="sr-only">
                Animations
              </label>
              <Switch
                id={motionId}
                checked={settings.animations}
                onCheckedChange={(animations) => settings.update({ animations })}
              />
            </span>
          </Row>
        </div>
      </DialogContent>
    </Dialog>
  );
}

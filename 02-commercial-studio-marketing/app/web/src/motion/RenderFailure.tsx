import { AlertTriangle, X } from "lucide-react";
import { Link } from "react-router-dom";
import { cn } from "../components/ui";
import { useI18n } from "../i18n";
import { isBudgetFailure, type RenderFailureInfo } from "./model";

/** A refused or failed render stays on the page (the toast of an API error is gone after a few seconds, and a failed job's card disappears when the job ends). */
export function RenderFailure({ failure, onDismiss }: { failure: RenderFailureInfo; onDismiss: () => void }) {
  const { t, tx } = useI18n();
  const budget = isBudgetFailure(failure);
  return (
    <div
      role="alert"
      data-testid="render-failure"
      data-kind={budget ? "budget" : "error"}
      className={cn("mt-3 flex items-start gap-3 rounded-xl border px-4 py-3 text-[13px]", budget ? "border-dawn-400/60 bg-dawn-300/10" : "border-roast-500/40 bg-roast-500/5")}
    >
      <AlertTriangle className={cn("mt-0.5 h-4 w-4 shrink-0", budget ? "text-dawn-700" : "text-roast-500")} aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <div className="font-semibold text-espresso-900">{budget ? t("Render refused by the AI budget") : t("Render failed")}</div>
        {failure.message && <p className="mt-0.5 break-words text-espresso-700">{failure.message}</p>}
        {failure.hint && <p className="mt-0.5 break-words text-espresso-500">{failure.hint}</p>}
        {budget && !failure.hint && (
          <p className="mt-1 text-espresso-600">
            {tx("Choose Preview, or raise the cap on the <cost>cost meter</cost> (admin only).", {
              cost: (chunks) => (
                <Link className="text-dawn-600 underline" to="/cost">
                  {chunks}
                </Link>
              ),
            })}
          </p>
        )}
      </div>
      <button type="button" onClick={onDismiss} aria-label={t("Close")} className="rounded p-1 hover:bg-cream-200">
        <X className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  );
}

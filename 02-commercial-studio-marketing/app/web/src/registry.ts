import type { ComponentType, ReactElement } from "react";
import type { LucideIcon } from "lucide-react";

export interface WorkspaceTabProps {
  campaign: any; // eslint-disable-line @typescript-eslint/no-explicit-any
  reload: () => void;
}

/** A feature slice contributes routes, a nav entry and/or campaign-workspace tabs. Auto-discovered below. */
export interface FeatureDef {
  id: string;
  routes?: { path: string; element: ReactElement }[];
  nav?: { group: string; label: string; to: string; order: number; icon: LucideIcon };
  workspaceTabs?: { id: string; label: string; order: number; Component: ComponentType<WorkspaceTabProps> }[];
}

const mods = import.meta.glob("./features/*/index.tsx", { eager: true }) as Record<string, { feature: FeatureDef }>;
export const featureDefs: FeatureDef[] = Object.values(mods)
  .map((m) => m.feature)
  .filter(Boolean);

export const workspaceTabs = featureDefs
  .flatMap((f) => f.workspaceTabs ?? [])
  .sort((a, b) => a.order - b.order);

export const NAV_GROUPS = ["Studio", "Brand Brain", "Review", "Performance", "Operate"];

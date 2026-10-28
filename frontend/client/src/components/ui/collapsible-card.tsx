import * as React from "react";
import { ChevronDown } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

interface CollapsibleCardProps {
  title: React.ReactNode;
  subtitle?: string;
  icon?: React.ReactNode;
  badge?: React.ReactNode;
  defaultOpen?: boolean;
  className?: string;
  headerClassName?: string;
  contentClassName?: string;
  children: React.ReactNode;
}

export function CollapsibleCard({
  title,
  subtitle,
  icon,
  badge,
  defaultOpen = true,
  className,
  headerClassName,
  contentClassName,
  children,
}: CollapsibleCardProps) {
  const [isOpen, setIsOpen] = React.useState(defaultOpen);

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <Card className={cn("bg-card border-border/50", className)}>
        <CollapsibleTrigger asChild>
          <CardHeader
            className={cn(
              "cursor-pointer select-none transition-colors hover:bg-muted/30",
              headerClassName
            )}
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                {icon}
                <div>
                  <CardTitle className="text-sm font-semibold flex items-center gap-2">
                    {title}
                    {badge}
                  </CardTitle>
                  {subtitle && (
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {subtitle}
                    </p>
                  )}
                </div>
              </div>
              <ChevronDown
                className={cn(
                  "w-4 h-4 text-muted-foreground transition-transform duration-200",
                  isOpen && "rotate-180"
                )}
              />
            </div>
          </CardHeader>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <CardContent className={cn("pt-0", contentClassName)}>
            {children}
          </CardContent>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  );
}





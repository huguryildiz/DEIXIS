import * as React from "react"
import { Tooltip as TooltipPrimitive } from "@base-ui/react/tooltip"
import { cn } from "cn"

// Wraps a single element (rendered as the trigger) and shows `content` on hover or keyboard focus.
function Tooltip({
  content,
  children,
  side = "top",
  className,
}: {
  content: React.ReactNode
  children: React.ReactElement
  side?: TooltipPrimitive.Positioner.Props["side"]
  className?: string
}) {
  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger delay={250} render={children} />
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Positioner side={side} sideOffset={6} collisionPadding={12} className="isolate z-80">
          <TooltipPrimitive.Popup
            data-slot="tooltip-content"
            className={cn(
              "max-w-72 origin-(--transform-origin) rounded-md bg-popover px-2.5 py-1.5 text-xs leading-snug text-popover-foreground shadow-md ring-1 ring-foreground/10 transition-[opacity,scale] duration-100 data-starting-style:scale-95 data-starting-style:opacity-0 data-ending-style:scale-95 data-ending-style:opacity-0",
              className
            )}
          >
            {content}
          </TooltipPrimitive.Popup>
        </TooltipPrimitive.Positioner>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  )
}

export { Tooltip }

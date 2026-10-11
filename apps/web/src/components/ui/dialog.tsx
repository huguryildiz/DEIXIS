import * as React from "react"
import { Dialog as DialogPrimitive } from "@base-ui/react/dialog"
import { XIcon } from "lucide-react"
import { cn } from "@/lib/utils"
import { t } from "@/i18n"

// The mockup's dialog shell (`.pal.dlg`): a scrim, a 480px card 14vh from the top, a head with an icon, the title and a
// close button, a body, and an optional footer on the sidebar surface. Theme follows html.dark like every portal.

function Dialog({ ...props }: DialogPrimitive.Root.Props) {
  return <DialogPrimitive.Root data-slot="dialog" {...props} />
}

function DialogContent({ icon, title, className, backdropClassName, children, showCloseButton = true, ...props }: DialogPrimitive.Popup.Props & {
  icon?: React.ReactNode
  title: React.ReactNode
  backdropClassName?: string
  showCloseButton?: boolean
}) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Backdrop data-slot="dialog-scrim" className={cn("dialog-scrim", backdropClassName)} />
      <DialogPrimitive.Popup data-slot="dialog-content" className={cn("dialog", className)} {...props}>
        <div className="dialog-head">
          {icon && <span className="dialog-icon">{icon}</span>}
          <DialogPrimitive.Title className="dialog-title">{title}</DialogPrimitive.Title>
          {showCloseButton && <DialogPrimitive.Close className="dialog-close" aria-label={t("Close")}><XIcon size={16} aria-hidden="true" /></DialogPrimitive.Close>}
        </div>
        {children}
      </DialogPrimitive.Popup>
    </DialogPrimitive.Portal>
  )
}

function DialogDescription({ className, ...props }: DialogPrimitive.Description.Props) {
  return <DialogPrimitive.Description data-slot="dialog-description" className={cn("dialog-description", className)} {...props} />
}

function DialogBody({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="dialog-body" className={cn("dialog-body", className)} {...props} />
}

function DialogFooter({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="dialog-footer" className={cn("dialog-footer", className)} {...props} />
}

export { Dialog, DialogContent, DialogDescription, DialogBody, DialogFooter }

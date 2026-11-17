"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
};

/** Names the consequence before the assistant is allowed to register the person. */
export function ConfirmRegistrationDialog({ open, onOpenChange, onConfirm }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Register this customer?</DialogTitle>
          <DialogDescription>
            This creates a customer record with the details now in the form. The assistant cannot
            undo it. The email address, phone number, and tax ID can belong to only one customer.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button type="button" variant="outline" className="h-10" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="button" className="h-10" onClick={onConfirm}>
            Confirm registration
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

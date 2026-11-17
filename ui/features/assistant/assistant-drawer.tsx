"use client";

import { MessageCircle } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: ReactNode;
};

/** On narrow screens the assistant opens from a floating button in a bottom drawer. */
export function AssistantDrawer({ open, onOpenChange, children }: Props) {
  return (
    <div className="lg:hidden">
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetTrigger asChild>
          <Button
            type="button"
            className="fixed right-4 bottom-4 z-40 h-12 rounded-full px-5 shadow-lg"
          >
            <MessageCircle aria-hidden="true" data-icon="inline-start" />
            Ask the assistant
          </Button>
        </SheetTrigger>
        <SheetContent side="bottom" className="max-h-[85vh] overflow-y-auto p-4">
          <SheetHeader className="p-0">
            <SheetTitle>Assistant</SheetTitle>
            <SheetDescription>Get help with errors, warnings, and the form.</SheetDescription>
          </SheetHeader>
          {children}
        </SheetContent>
      </Sheet>
    </div>
  );
}

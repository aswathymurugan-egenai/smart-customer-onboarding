import type { ProblemDetails } from "@/lib/api";

import { FIELD_PATHS, type FieldPath } from "./schema";

export const DUPLICATE_MESSAGE = "Already registered to another customer";

export type FieldProblem = { field: FieldPath; message: string };

export type ProblemBanner = {
  title: string;
  detail: string;
  /** True when trying the same request again can succeed. */
  retryable: boolean;
};

export type ProblemOutcome = {
  fieldErrors: FieldProblem[];
  banner: ProblemBanner | null;
};

const MATCHED_FIELD: Record<string, FieldPath> = {
  email: "email",
  phone: "phone",
  tax_id: "tax_id",
};

/** `/address/city` becomes `address.city`. Returns null for a pointer the form has no field for. */
export function pointerToField(pointer: string): FieldPath | null {
  const path = pointer.replace(/^\//, "").split("/").join(".");
  return (FIELD_PATHS as readonly string[]).includes(path) ? (path as FieldPath) : null;
}

function retryAfterText(seconds: number | null): string {
  if (seconds === null) return "Wait a moment and try again.";
  if (seconds >= 120) return `Try again in about ${Math.ceil(seconds / 60)} minutes.`;
  return `Try again in ${seconds} ${seconds === 1 ? "second" : "seconds"}.`;
}

/**
 * Turn an error response into messages under fields and, when no field fits, a banner.
 * The 409 names which unique keys matched, and a 422 points at the offending fields.
 */
export function interpretProblem(
  status: number,
  problem: ProblemDetails | undefined,
  retryAfterHeader: string | null,
): ProblemOutcome {
  const retryAfter = retryAfterHeader !== null && /^\d+$/.test(retryAfterHeader)
    ? Number(retryAfterHeader)
    : null;

  if (status === 409 && problem?.matched_on) {
    return {
      fieldErrors: problem.matched_on.map((key) => ({
        field: MATCHED_FIELD[key],
        message: DUPLICATE_MESSAGE,
      })),
      banner: null,
    };
  }

  if (status === 422 && problem) {
    const fieldErrors: FieldProblem[] = [];
    const unplaced: string[] = [];
    for (const error of problem.errors ?? []) {
      const field = pointerToField(error.pointer);
      if (field) fieldErrors.push({ field, message: error.message });
      else unplaced.push(error.message);
    }
    if (fieldErrors.length > 0 && unplaced.length === 0) return { fieldErrors, banner: null };
    return {
      fieldErrors,
      banner: {
        title: problem.title,
        detail: unplaced[0] ?? problem.detail,
        retryable: false,
      },
    };
  }

  if (status === 429) {
    return {
      fieldErrors: [],
      banner: {
        title: "Too many attempts",
        detail: `You have tried this too often. ${retryAfterText(retryAfter)}`,
        retryable: false,
      },
    };
  }

  if (status === 503) {
    return {
      fieldErrors: [],
      banner: {
        title: "Registration is busy",
        detail: `Many people are registering right now. ${retryAfterText(retryAfter)}`,
        retryable: true,
      },
    };
  }

  if (status === 403) {
    return {
      fieldErrors: [],
      banner: {
        title: "Verification failed",
        detail: "We could not verify this request. Reload the page and try again.",
        retryable: false,
      },
    };
  }

  return {
    fieldErrors: [],
    banner: {
      title: "Something went wrong",
      detail: "The request could not be completed. Try again in a moment.",
      retryable: true,
    },
  };
}

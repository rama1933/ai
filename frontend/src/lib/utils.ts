import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

/**
 * Merge Tailwind classes with conflict resolution, so a component's default
 * classes can be overridden by a caller's without both landing in the output.
 * Every shadcn-vue component imports this.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}

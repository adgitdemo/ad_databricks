/**
 * Lightweight, mobile-first UI primitives (Tailwind + design tokens from
 * `@databricks/appkit-ui/styles.css`). These replace the appkit-ui React
 * components so the client bundle doesn't pull in Radix/chart/Arrow deps —
 * keeping the app fast to load in the Genie One mobile browser.
 *
 * Interactive bits use native elements (`<select>`, `<details>`) instead of
 * Radix to stay tiny and touch-friendly.
 */
import type { ComponentProps, ReactNode } from 'react';
import { cn } from '@/lib/utils';

// --- Button -----------------------------------------------------------------
export type ButtonVariant = 'default' | 'secondary' | 'outline' | 'ghost' | 'destructive';
export type ButtonSize = 'default' | 'sm' | 'icon';

const BUTTON_BASE =
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50';

const BUTTON_VARIANT: Record<ButtonVariant, string> = {
  default: 'bg-primary text-primary-foreground hover:bg-primary/90',
  secondary: 'bg-secondary text-secondary-foreground hover:bg-secondary/80',
  outline: 'border border-input bg-background hover:bg-muted',
  ghost: 'hover:bg-muted',
  destructive: 'bg-destructive text-destructive-foreground hover:bg-destructive/90',
};

const BUTTON_SIZE: Record<ButtonSize, string> = {
  // Comfortable ~44px tap targets on touch screens.
  default: 'h-11 sm:h-10 px-4 py-2',
  sm: 'h-9 px-3',
  icon: 'h-11 w-11 sm:h-10 sm:w-10',
};

export function buttonClasses(
  variant: ButtonVariant = 'default',
  size: ButtonSize = 'default',
  className?: string,
): string {
  return cn(BUTTON_BASE, BUTTON_VARIANT[variant], BUTTON_SIZE[size], className);
}

export function Button({
  variant = 'default',
  size = 'default',
  className,
  ...props
}: ComponentProps<'button'> & { variant?: ButtonVariant; size?: ButtonSize }) {
  return <button className={buttonClasses(variant, size, className)} {...props} />;
}

// --- Card --------------------------------------------------------------------
export function Card({ className, ...props }: ComponentProps<'div'>) {
  return (
    <div
      className={cn('rounded-lg border bg-card text-card-foreground shadow-sm', className)}
      {...props}
    />
  );
}
export function CardHeader({ className, ...props }: ComponentProps<'div'>) {
  return <div className={cn('flex flex-col gap-1.5 p-4 sm:p-5', className)} {...props} />;
}
export function CardTitle({ className, ...props }: ComponentProps<'h3'>) {
  return <h3 className={cn('font-semibold leading-tight', className)} {...props} />;
}
export function CardDescription({ className, ...props }: ComponentProps<'p'>) {
  return <p className={cn('text-sm text-muted-foreground', className)} {...props} />;
}
export function CardContent({ className, ...props }: ComponentProps<'div'>) {
  return <div className={cn('p-4 pt-0 sm:p-5 sm:pt-0', className)} {...props} />;
}

// --- Form controls -----------------------------------------------------------
export function Input({ className, ...props }: ComponentProps<'input'>) {
  return (
    <input
      // text-base (16px) on mobile prevents iOS zoom-on-focus.
      className={cn(
        'flex h-11 sm:h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-base sm:text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50',
        className,
      )}
      {...props}
    />
  );
}
export function Textarea({ className, ...props }: ComponentProps<'textarea'>) {
  return (
    <textarea
      className={cn(
        'flex w-full rounded-md border border-input bg-background px-3 py-2 text-base sm:text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50',
        className,
      )}
      {...props}
    />
  );
}
export function Label({ className, ...props }: ComponentProps<'label'>) {
  return <label className={cn('text-sm font-medium', className)} {...props} />;
}
export function Select({ className, ...props }: ComponentProps<'select'>) {
  return (
    <select
      className={cn(
        'h-11 sm:h-10 w-full rounded-md border border-input bg-background px-3 text-base sm:text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        className,
      )}
      {...props}
    />
  );
}

// --- Badge -------------------------------------------------------------------
export type BadgeVariant = 'default' | 'secondary' | 'outline' | 'destructive';
const BADGE_VARIANT: Record<BadgeVariant, string> = {
  default: 'border-transparent bg-primary text-primary-foreground',
  secondary: 'border-transparent bg-secondary text-secondary-foreground',
  outline: 'text-foreground',
  destructive: 'border-transparent bg-destructive text-destructive-foreground',
};
export function Badge({
  variant = 'default',
  className,
  ...props
}: ComponentProps<'span'> & { variant?: BadgeVariant }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium',
        BADGE_VARIANT[variant],
        className,
      )}
      {...props}
    />
  );
}

// --- Alert -------------------------------------------------------------------
export function Alert({
  variant = 'default',
  className,
  ...props
}: ComponentProps<'div'> & { variant?: 'default' | 'destructive' }) {
  return (
    <div
      role="alert"
      className={cn(
        'flex gap-2 rounded-md border p-3 text-sm',
        variant === 'destructive' ? 'border-destructive/50 text-destructive' : 'bg-card',
        className,
      )}
      {...props}
    />
  );
}
export function AlertDescription({ className, ...props }: ComponentProps<'div'>) {
  return <div className={cn('text-sm [&_p]:leading-relaxed', className)} {...props} />;
}

// --- Disclosure (native <details>) ------------------------------------------
export function Disclosure({
  summary,
  children,
  className,
}: {
  summary: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <details className={cn('group', className)}>
      <summary className="flex cursor-pointer list-none items-center gap-1 py-1 text-xs text-muted-foreground marker:hidden">
        <span className="transition-transform group-open:rotate-90">▸</span>
        {summary}
      </summary>
      <div className="space-y-4 pt-2">{children}</div>
    </details>
  );
}

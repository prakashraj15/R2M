"use client";
// One motion vocabulary for both apps: short, eased, interruptible, and off when the OS asks for reduced motion.
import { AnimatePresence, MotionConfig, motion, type Transition } from "framer-motion";
import type { ReactNode } from "react";

export const ease: Transition = { duration: 0.22, ease: [0.22, 1, 0.36, 1] };

export function MotionRoot({ children }: { children: ReactNode }) {
  return (
    <MotionConfig reducedMotion="user" transition={ease}>
      {children}
    </MotionConfig>
  );
}

/** Route content cross-fade + slight rise, keyed by pathname. */
export function PageTransition({ id, children }: { id: string; children: ReactNode }) {
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={id}
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -4 }}
        transition={ease}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}

/** Children rise in one after another (cards, lists). */
export function Stagger({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <motion.div
      className={className}
      initial="hidden"
      animate="show"
      variants={{ hidden: {}, show: { transition: { staggerChildren: 0.05 } } }}
    >
      {children}
    </motion.div>
  );
}

export const rise = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0, transition: ease },
};

export { AnimatePresence, motion };

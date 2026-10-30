import { createElement } from "react"

export const Link = ({ to, children, ...props }) => createElement("a", { href: to, ...props }, children)

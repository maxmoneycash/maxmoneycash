// Central GSAP entry for the landing page. Import gsap ONLY through this
// module (from ui/marketing/v3/*) so the library stays inside the lazy
// LandingPage chunk — never in the dashboard/main bundle.
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

gsap.registerPlugin(ScrollTrigger);

export { gsap, ScrollTrigger };

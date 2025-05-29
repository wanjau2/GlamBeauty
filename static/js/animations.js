document.addEventListener('DOMContentLoaded', function() {
    // Add page transition class to main content
    const mainContent = document.querySelector('main');
    if (mainContent) {
        mainContent.classList.add('page-transition');
    }
    
    // Initialize fade-in animations
    initFadeInElements();
    
    // Initialize any other animations
    initCounterAnimations();
});

// Fade in elements as they scroll into view
function initFadeInElements() {
    const fadeElements = document.querySelectorAll('.fade-in');
    
    // If IntersectionObserver is supported
    if ('IntersectionObserver' in window) {
        const fadeObserver = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.classList.add('visible');
                    fadeObserver.unobserve(entry.target);
                }
            });
        }, { threshold: 0.1 });
        
        fadeElements.forEach(element => {
            fadeObserver.observe(element);
        });
    } else {
        // Fallback for browsers that don't support IntersectionObserver
        fadeElements.forEach(element => {
            element.classList.add('visible');
        });
    }
}

// Animate counters (for statistics, etc.)
function initCounterAnimations() {
    const counters = document.querySelectorAll('.counter-value');
    
    counters.forEach(counter => {
        const target = parseInt(counter.getAttribute('data-target'));
        if (isNaN(target)) return;
        
        const duration = 1500; // milliseconds
        const step = target / (duration / 16); // 60fps
        
        let current = 0;
        const updateCounter = () => {
            current += step;
            if (current < target) {
                counter.textContent = Math.ceil(current);
                requestAnimationFrame(updateCounter);
            } else {
                counter.textContent = target;
            }
        };
        
        // Start animation when element is in view
        if ('IntersectionObserver' in window) {
            const observer = new IntersectionObserver((entries) => {
                if (entries[0].isIntersecting) {
                    updateCounter();
                    observer.unobserve(counter);
                }
            }, { threshold: 0.5 });
            
            observer.observe(counter);
        } else {
            updateCounter();
        }
    });
}

// Add hover effects for navigation links
function initNavHoverEffects() {
    const navLinks = document.querySelectorAll('.navbar-nav .nav-link');
    
    navLinks.forEach(link => {
        link.addEventListener('mouseenter', function() {
            this.classList.add('nav-hover');
        });
        
        link.addEventListener('mouseleave', function() {
            this.classList.remove('nav-hover');
        });
    });
}

// Initialize all animations
initNavHoverEffects();
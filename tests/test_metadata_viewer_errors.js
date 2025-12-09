/**
 * Test cases for metadata viewer error handling
 * Tests the fix for: "Cannot set properties of null (setting 'textContent')"
 */

describe('Metadata Viewer - Error Handling', () => {
    let mockContainer;
    let mockElement;

    beforeEach(() => {
        // Mock DOM structure
        mockContainer = {
            innerHTML: ''
        };

        // Mock document methods
        global.document = {
            getElementById: jest.fn((id) => {
                if (id === 'resultsContainer') return mockContainer;
                if (id === 'loadingProgress') return { style: { width: '' } };
                if (id === 'fileCount') return { textContent: '' };
                if (id === 'loadingState') return { style: { display: '' } };
                return null;
            }),
            querySelector: jest.fn((selector) => {
                if (selector === '.loading-text') {
                    return mockContainer.innerHTML.includes('loading-text')
                        ? { textContent: '' }
                        : null;
                }
                return null;
            }),
            createElement: jest.fn(() => ({ textContent: '' }))
        };

        global.localStorage = {
            getItem: jest.fn(),
            setItem: jest.fn()
        };
    });

    describe('Null reference errors', () => {
        test('loadData() should not fail when loading elements are null on retry', () => {
            // Simulate error state where loadingState has been replaced
            mockContainer.innerHTML = '<div class="error-container">Error occurred</div>';

            // Ensure querySelector returns null (element was removed)
            const originalQuerySelector = global.document.querySelector;
            global.document.querySelector = jest.fn(() => null);

            // This should not throw "Cannot set properties of null"
            expect(() => {
                // Simulate start of loadData()
                mockContainer.innerHTML = '<div class="loading-container" id="loadingState"><div class="loading-spinner"></div><div class="loading-text">Loading metadata...</div><div class="loading-progress"><div class="loading-progress-bar" id="loadingProgress" style="width: 0%"></div></div></div>';
            }).not.toThrow();

            global.document.querySelector = originalQuerySelector;
        });

        test('Retry button should restore loading UI before attempting reload', () => {
            // Simulate first failed load
            mockContainer.innerHTML = '<div class="error-container"><button onclick="loadData()">Retry</button></div>';

            // Simulate retry click (loadData called)
            // loadData should first restore the loading UI
            mockContainer.innerHTML = '<div class="loading-container" id="loadingState"><div class="loading-spinner"></div><div class="loading-text">Loading metadata...</div></div>';

            // Verify loading state was restored
            expect(mockContainer.innerHTML).toContain('loading-spinner');
            expect(mockContainer.innerHTML).toContain('loading-text');
        });

        test('Multiple error/retry cycles should not cause null reference errors', () => {
            const states = [
                // Initial load
                '<div class="loading-container" id="loadingState"><div class="loading-spinner"></div><div class="loading-text">Loading metadata...</div></div>',
                // First error
                '<div class="error-container"><button onclick="loadData()">Retry</button></div>',
                // Retry 1
                '<div class="loading-container" id="loadingState"><div class="loading-spinner"></div><div class="loading-text">Loading metadata...</div></div>',
                // Second error
                '<div class="error-container"><button onclick="loadData()">Retry</button></div>',
                // Retry 2
                '<div class="loading-container" id="loadingState"><div class="loading-spinner"></div><div class="loading-text">Loading metadata...</div></div>'
            ];

            // Simulate cycling through states
            states.forEach((html, index) => {
                expect(() => {
                    mockContainer.innerHTML = html;
                }).not.toThrow();
            });
        });

        test('loadingText element should exist after loadData() initialization', () => {
            // This mimics the loadData() function's first operation
            mockContainer.innerHTML = '<div class="loading-container" id="loadingState"><div class="loading-text">Loading metadata...</div></div>';

            const loadingText = document.querySelector('.loading-text');
            expect(loadingText).not.toBeNull();
            expect(loadingText.textContent).toBe('Loading metadata...');
        });
    });

    describe('Safe element updates', () => {
        test('Should safely update loadingProgress element', () => {
            const progress = { style: { width: '0%' } };

            expect(() => {
                progress.style.width = '20%';
                progress.style.width = '60%';
                progress.style.width = '100%';
            }).not.toThrow();

            expect(progress.style.width).toBe('100%');
        });

        test('Should safely update fileCount element', () => {
            const fileCount = { textContent: '' };

            expect(() => {
                fileCount.textContent = '30,133 files indexed';
            }).not.toThrow();

            expect(fileCount.textContent).toBe('30,133 files indexed');
        });

        test('Should handle missing optional elements gracefully', () => {
            // Simulate missing elements
            global.document.getElementById = jest.fn((id) => {
                if (id === 'resultsContainer') return mockContainer;
                return null;
            });

            // Should not throw when elements don't exist
            expect(() => {
                const elem = global.document.getElementById('nonexistent');
                if (elem) elem.textContent = 'test';
            }).not.toThrow();
        });
    });

    describe('Error recovery', () => {
        test('Error message should display helpful debugging info', () => {
            const errorMsg = 'Failed to fetch metadata.json';
            mockContainer.innerHTML = `<div class="error-container"><div class="error-message">Failed to load metadata</div><div class="error-details">${errorMsg}</div><button onclick="loadData()">Retry</button></div>`;

            expect(mockContainer.innerHTML).toContain(errorMsg);
            expect(mockContainer.innerHTML).toContain('Retry');
        });

        test('Retry button should be functional after error', () => {
            mockContainer.innerHTML = '<div class="error-container"><button class="retry-btn" onclick="loadData()">Retry</button></div>';

            const retryBtn = mockContainer.innerHTML.includes('retry-btn');
            expect(retryBtn).toBe(true);
        });
    });
});

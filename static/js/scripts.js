document.addEventListener('DOMContentLoaded', function() {
    const nameInput = document.getElementById('name');
    const tickerInput = document.getElementById('ticker');
    const resultsContainer = document.getElementById('search-results-container');
    let searchTimeout;

    if (nameInput) {
        nameInput.addEventListener('input', function() {
            // Clear previous timeout
            clearTimeout(searchTimeout);
            const query = nameInput.value;

            if (query.length < 3) {
                resultsContainer.innerHTML = '';
                resultsContainer.style.display = 'none';
                return;
            }

            // Set a new timeout to avoid spamming the server
            searchTimeout = setTimeout(() => {
                fetch(`/api/search?q=${encodeURIComponent(query)}`)
                    .then(response => response.json())
                    .then(data => {
                        if (data && data.length > 0) {
                            resultsContainer.innerHTML = '';
                            resultsContainer.style.display = 'block';

                            const list = document.createElement('ul');
                            data.forEach(item => {
                                const listItem = document.createElement('li');
                                listItem.textContent = `${item.name} (${item.ticker})`;
                                listItem.dataset.name = item.name;
                                listItem.dataset.ticker = item.ticker;
                                
                                listItem.addEventListener('click', function() {
                                    nameInput.value = this.dataset.name;
                                    tickerInput.value = this.dataset.ticker;
                                    resultsContainer.innerHTML = '';
                                    resultsContainer.style.display = 'none';
                                });
                                list.appendChild(listItem);
                            });
                            resultsContainer.appendChild(list);
                        } else {
                            resultsContainer.innerHTML = '';
                            resultsContainer.style.display = 'none';
                        }
                    })
                    .catch(error => {
                        console.error('Error fetching search results:', error);
                        resultsContainer.innerHTML = '';
                        resultsContainer.style.display = 'none';
                    });
            }, 300); // Wait 300ms after user stops typing
        });
    }

    // Hide results if user clicks outside
    document.addEventListener('click', function(e) {
        if (!resultsContainer.contains(e.target) && e.target !== nameInput) {
            resultsContainer.style.display = 'none';
        }
    });
});

"""
Modern Terminal User Interface for moviebox-api
Beautiful TUI with rich library for enhanced user experience
"""

import asyncio
import sys
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt, Confirm
from rich.layout import Layout
from rich.live import Live
from rich.text import Text
from rich import box
from rich.columns import Columns
from rich.padding import Padding

from moviebox_api.core import Search
from moviebox_api.requests import Session
from moviebox_api.constants import SubjectType

# Initialize rich console
console = Console()


class MovieBoxTUI:
    """Main TUI Application"""
    
    def __init__(self):
        self.session = Session()
        self.current_page = 1
        self.per_page = 5
        
    def show_header(self):
        """Display beautiful header"""
        header = Text()
        header.append("🎬 MOVIEBOX ", style="bold red")
        header.append("- Stream Movies & TV Shows", style="bold white")
        
        console.print(Panel(
            header,
            box=box.DOUBLE,
            border_style="red",
            padding=(1, 2)
        ))
    
    def show_main_menu(self) -> str:
        """Display main menu and get user choice"""
        console.print("\n")
        
        table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
        table.add_column("Option", style="cyan bold", width=8)
        table.add_column("Description", style="white")
        
        table.add_row("1", "🎬 Search Movies")
        table.add_row("2", "📺 Search TV Series")
        table.add_row("3", "🎨 Search Animation")
        table.add_row("4", "📚 Search All Content")
        table.add_row("5", "⭐ Trending")
        table.add_row("0", "🚪 Exit")
        
        console.print(table)
        
        choice = Prompt.ask(
            "\n[bold cyan]Choose an option[/bold cyan]",
            choices=["0", "1", "2", "3", "4", "5"],
            default="1"
        )
        return choice
    
    def search_content(self, subject_type: SubjectType) -> None:
        """Search and display content"""
        # Get search query
        if subject_type == SubjectType.MOVIES:
            type_name = "Movies"
        elif subject_type == SubjectType.TV_SERIES:
            type_name = "TV Series"
        else:
            type_name = "Content"
        
        console.print(f"\n[bold cyan]🔍 Search {type_name}[/bold cyan]\n")
        query = Prompt.ask(f"[yellow]Enter {type_name.lower()} title[/yellow]")
        
        if not query.strip():
            console.print("[red]❌ Search query cannot be empty![/red]")
            return
        
        # Search with progress indicator
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task(f"[cyan]Searching for '{query}'...", total=None)
            
            try:
                from moviebox_api.helpers import get_event_loop
                
                search = Search(self.session, query, subject_type, page=1, per_page=self.per_page)
                results = get_event_loop().run_until_complete(search.get_content_model())
                
                progress.update(task, completed=True)
            except Exception as e:
                console.print(f"\n[red]❌ Error: {e}[/red]")
                return
        
        if not results.items:
            console.print("\n[yellow]No results found.[/yellow]")
            return
        
        # Display results with pagination
        self.display_results_paginated(results, subject_type, query)
    
    def display_results_paginated(self, results, subject_type, query):
        """Display results with pagination"""
        current_page = results.pager.page
        
        while True:
            console.clear()
            self.show_header()
            
            # Results header - show actual items on this page
            page_info = f"Page {current_page}"
            
            # Show total and estimated pages
            total_count = results.pager.totalCount
            estimated_pages = (total_count + self.per_page - 1) // self.per_page
            items_on_page = len(results.items)
            
            if results.pager.hasMore:
                page_info += f" of ~{estimated_pages}+"
            else:
                page_info += f" of {estimated_pages}"
            
            console.print(f"\n[bold white]Showing {items_on_page} items on this page | Total found: {total_count} | {page_info}[/bold white]\n")
            
            # Display results table
            table = Table(
                show_header=True,
                header_style="bold cyan",
                box=box.ROUNDED,
                padding=(0, 1)
            )
            
            table.add_column("#", style="dim", width=4)
            table.add_column("Title", style="bold white", no_wrap=False)
            table.add_column("Year", style="cyan", width=6)
            table.add_column("Rating", style="yellow", width=8)
            table.add_column("Genre", style="green", no_wrap=False)
            
            for idx, item in enumerate(results.items, 1):
                genres = ", ".join(item.genre[:2]) if len(item.genre) > 0 else "N/A"
                table.add_row(
                    str(idx),
                    item.title,
                    str(item.releaseDate.year),
                    f"⭐ {item.imdbRatingValue}",
                    genres
                )
            
            console.print(table)
            
            # Navigation options - use hasMore from API
            console.print("\n[bold]Options:[/bold]")
            options_text = "[cyan]1-{}[/cyan] Select item".format(len(results.items))
            
            if current_page > 1:
                options_text += " | [cyan]P[/cyan] Previous page"
            
            # Only show Next if API says there's more
            if results.pager.hasMore:
                options_text += " | [cyan]N[/cyan] Next page"
            
            options_text += " | [cyan]0[/cyan] Back to menu"
            
            console.print(options_text)
            
            # Get user choice
            choice = Prompt.ask("\n[bold cyan]Choose[/bold cyan]").strip().upper()
            
            if choice == "0":
                return
            elif choice == "N" and results.pager.hasMore:
                # Next page - only if API says there's more
                try:
                    current_page += 1
                    new_results = self._fetch_page(query, subject_type, current_page)
                    # Only update if we actually got results
                    if new_results and new_results.items:
                        results = new_results
                    else:
                        raise Exception("No items on this page")
                except Exception as e:
                    console.print(f"\n[yellow]⚠️  No more results available[/yellow]")
                    console.print(f"[dim]API indicated more pages but they're empty[/dim]")
                    current_page -= 1  # Go back to previous page
                    # Update hasMore to false so "N" option won't show again
                    results.pager.hasMore = False
                    console.input("\nPress Enter to continue...")
            elif choice == "P" and current_page > 1:
                # Previous page
                try:
                    current_page -= 1
                    results = self._fetch_page(query, subject_type, current_page)
                except Exception as e:
                    console.print(f"\n[red]❌ Error loading page: {e}[/red]")
                    current_page += 1  # Go back
                    console.input("\nPress Enter to continue...")
            elif choice.isdigit() and 1 <= int(choice) <= len(results.items):
                # Select item
                selected_item = results.items[int(choice) - 1]
                self.show_item_details(selected_item, subject_type)
            else:
                console.print("[red]Invalid choice![/red]")
                console.input("\nPress Enter to continue...")
    
    def _fetch_page(self, query, subject_type, page):
        """Fetch a specific page of results"""
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task(f"[cyan]Loading page {page}...", total=None)
            
            from moviebox_api.helpers import get_event_loop
            
            search = Search(self.session, query, subject_type, page=page, per_page=self.per_page)
            results = get_event_loop().run_until_complete(search.get_content_model())
            
            progress.update(task, completed=True)
        
        return results
    
    def show_item_details(self, item, subject_type):
        """Show detailed information about selected item"""
        console.clear()
        self.show_header()
        
        # Create details panel
        details = Text()
        details.append(f"\n{item.title}\n", style="bold white")
        details.append(f"Year: {item.releaseDate.year}\n", style="cyan")
        details.append(f"Rating: ⭐ {item.imdbRatingValue}/10\n", style="yellow")
        details.append(f"Genre: {', '.join(item.genre[:5])}\n\n", style="green")
        
        if item.description:
            desc = item.description[:300] + "..." if len(item.description) > 300 else item.description
            details.append(f"{desc}\n", style="white")
        
        console.print(Panel(
            details,
            title="[bold cyan]Details[/bold cyan]",
            border_style="cyan",
            padding=(1, 2)
        ))
        
        # Show options
        console.print("\n[bold]Actions:[/bold]")
        table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
        table.add_column("Option", style="cyan bold", width=8)
        table.add_column("Description", style="white")
        
        table.add_row("1", "▶️  Stream (Watch Now)")
        table.add_row("2", "⬇️  Download")
        if subject_type == SubjectType.TV_SERIES:
            table.add_row("3", "📺 View Episodes")
        table.add_row("0", "← Back")
        
        console.print(table)
        
        # STREAMLINED UX: Check if TV series and route directly to episodes
        if item.subjectType == SubjectType.TV_SERIES:
            # Go directly to episode listing  
            self.show_episodes(item)
            return
        
        # For movies: show normal action choices
        choices = ["0", "1", "2"]
        if subject_type == SubjectType.TV_SERIES:
            choices.append("3")
        
        choice = Prompt.ask("\n[bold cyan]Choose action[/bold cyan]", choices=choices, default="0")
        
        if choice == "1":
            self.stream_content(item, subject_type)
        elif choice == "2":
            self.download_content(item, subject_type)
        elif choice == "3" and subject_type == SubjectType.TV_SERIES:
            self.show_episodes(item)
    
    def get_quality_selection(self) -> str:
        """Get quality preference from user"""
        console.print("\n[bold]Select Quality:[/bold]")
        table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
        table.add_column("Option", style="cyan bold", width=8)
        table.add_column("Quality", style="white")
        
        table.add_row("1", "🎬 Best Quality (Recommended)")
        table.add_row("2", "1080p Full HD")
        table.add_row("3", "720p HD")
        table.add_row("4", "480p SD")
        
        console.print(table)
        
        choice = Prompt.ask("[bold cyan]Quality[/bold cyan]", choices=["1", "2", "3", "4"], default="1")
        quality_map = {"1": "BEST", "2": "1080P", "3": "720P", "4": "480P"}
        return quality_map[choice]
    
    def get_subtitle_preferences(self) -> tuple:
        """Get subtitle language preferences"""
        want_subs = Confirm.ask("\n[bold cyan]Enable subtitles?[/bold cyan]", default=True)
        
        if not want_subs:
            return False, []
        
        console.print("\n[bold]Subtitle Language:[/bold]")
        table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
        table.add_column("Option", style="cyan bold", width=8)
        table.add_column("Language", style="white")
        
        table.add_row("1", "🇮🇩 Indonesian")
        table. add_row("2", "🇬🇧 English")
        table.add_row("3", "🇪🇸 Spanish")
        table.add_row("4", "🇫🇷 French")
        table.add_row("5", "Custom")
        
        console.print(table)
        
        choice = Prompt.ask("[bold cyan]Language[/bold cyan]", choices=["1", "2", "3", "4", "5"], default="1")
        lang_map = {"1": "Indonesian", "2": "English", "3": "Spanish", "4": "French"}
        
        if choice == "5":
            custom_lang = Prompt.ask("[bold cyan]Enter language name[/bold cyan]")
            return True, [custom_lang]
        else:
            return True, [lang_map[choice]]
    
    def get_aspect_ratio_preference(self) -> str:
        """Get video aspect ratio preference from user"""
        console.print("\n[bold]Video Display Mode:[/bold]")
        
        table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
        table.add_column("Option", style="cyan bold", width=8)
        table.add_column("Description", style="white")
        
        table.add_row("1", "📺 Original (Recommended)")
        table.add_row("2", "⬛ Fullscreen")  
        table.add_row("3", "🎬 16:9")
        table.add_row("4", "📱 4:3")
        
        console.print(table)
        
        choice = Prompt.ask(
            "[bold cyan]Display[/bold cyan]",
            choices=["1", "2", "3", "4"],
            default="1"
        )
        
        aspect_map = {"1": "no", "2": "-1", "3": "16:9", "4": "4:3"}
        return aspect_map[choice]
    
    def download_content(self, item, subject_type):
        """Download movie or TV episode"""
        console.print(f"\n[bold yellow]⬇️  Downloading: {item.title}[/bold yellow]\n")
        
        # Get preferences
        quality = self.get_quality_selection()
        download_subs, languages = self.get_subtitle_preferences()
        
        # Confirmation
        console.print("\n[bold]Download Settings:[/bold]")
        console.print(f"[green]✓ Quality: {quality}[/green]")
        console.print(f"[green]✓ Subtitles: {languages[0] if download_subs else 'Disabled'}[/green]")
        
        if not Confirm.ask("\n[bold cyan]Start download?[/bold cyan]", default=True):
            return
        
        # Import downloader
        try:
            from moviebox_api.cli.downloader import Downloader
            from moviebox_api.helpers import get_event_loop
            
            console.print("\n[yellow]Starting download...[/yellow]")
            console.print("[dim]This will use the CLI download functionality[/dim]\n")
            
            downloader = Downloader()
            
            if subject_type == SubjectType.MOVIES:
                # Download movie
                get_event_loop().run_until_complete(
                    downloader.download_movie(
                        item.title,
                        year=item.releaseDate.year,
                        yes=True,
                        quality=quality,
                        language=languages if download_subs else [],
                        download_caption=download_subs
                    )
                )
            else:
                # For TV series, need season/episode
                season = int(Prompt.ask("[bold cyan]Season number[/bold cyan]", default="1"))
                episode = int(Prompt.ask("[bold cyan]Episode number[/bold cyan]", default="1"))
                
                get_event_loop().run_until_complete(
                    downloader.download_tv_series(
                        item.title,
                        year=item.releaseDate.year,
                        season=season,
                        episode=episode,
                        yes=True,
                        quality=quality,
                        language=languages if download_subs else [],
                        download_caption=download_subs,
                        limit=1
                    )
                )
            
            console.print("\n[bold green]✓ Download complete![/bold green]")
            
        except Exception as e:
            console.print(f"\n[red]❌ Download error: {e}[/red]")
        
        console.input("\nPress Enter to continue...")
    
    def stream_content(self, item, subject_type):
        """Stream selected content"""
        console.print(f"\n[bold yellow]🎬 Streaming: {item.title}[/bold yellow]\n")
        
        # Get preferences
        quality = self.get_quality_selection()
        want_subs, languages = self.get_subtitle_preferences()
        
        # Check for media player
        import shutil
        player = None
        players = ["mpv", "vlc", "mplayer"]
        
        console.print("\n[bold]Available Players:[/bold]")
        available_players = []
        for p in players:
            if shutil.which(p):
                available_players.append(p)
                console.print(f"[green]✓ {p.upper()}[/green]")
        
        if not available_players:
            console.print("\n[red]❌ No media player found[/red]")
            console.print("[yellow]Please install: mpv, vlc, or mplayer[/yellow]")
            console.print("[dim]  sudo pacman -S mpv  # Arch[/dim]")
            console.print("[dim]  sudo apt install mpv  # Ubuntu[/dim]")
            console.input("\nPress Enter to continue...")
            return
        
        # Select player
        if len(available_players) == 1:
            player = available_players[0]
        else:
            console.print("\n[bold]Select Player:[/bold]")
            for idx, p in enumerate(available_players, 1):
                console.print(f"[cyan]{idx}[/cyan] {p.upper()}")
            
            player_choice = Prompt.ask(
                "[bold cyan]Player[/bold cyan]",
                choices=[str(i) for i in range(1, len(available_players) + 1)],
                default="1"
            )
            player = available_players[int(player_choice) - 1]
        
        console.print(f"\n[green]✓ Using {player.upper()} player[/green]")
        console.print(f"[green]✓ Quality: {quality}[/green]")
        if want_subs:
            console.print(f"[green]✓ Subtitles: {languages[0]}[/green]")
        
        # Use CLI streaming
        try:
            from moviebox_api.cli.downloader import Downloader
            from moviebox_api.helpers import get_event_loop
            
            console.print(f"\n[bold yellow]Streaming: {item.title}[/bold yellow]")
            console.print("[dim]Press Ctrl+C in player to stop[/dim]\n")
            
            downloader = Downloader()
            
            if subject_type == SubjectType.MOVIES:
                get_event_loop().run_until_complete(
                    downloader.download_movie(
                        item.title,
                        year=item.releaseDate.year,
                        yes=True,
                        quality=quality,
                        language=languages if want_subs else [],
                        download_caption=want_subs,
                        stream_via=player
                    )
                )
            else:
                # For TV series
                season = int(Prompt.ask("[bold cyan]Season number[/bold cyan]", default="1"))
                episode = int(Prompt.ask("[bold cyan]Episode number[/bold cyan]", default="1"))
                
                get_event_loop().run_until_complete(
                    downloader.download_tv_series(
                        item.title,
                        year=item.releaseDate.year,
                        season=season,
                        episode=episode,
                        yes=True,
                        quality=quality,
                        language=languages if want_subs else [],
                        download_caption=want_subs,
                        stream_via=player,
                        limit=1
                    )
                )
        
        except KeyboardInterrupt:
            console.print("\n\n[yellow]Streaming stopped[/yellow]")
        except Exception as e:
            console.print(f"\n[red]❌ Streaming error: {e}[/red]")
        
        console.input("\nPress Enter to continue...")
    
    def show_episodes(self, item):
        """Show episodes for TV series with full season/episode listing"""
        console.clear()
        self.show_header()
        
        console.print(f"\n[bold white]{item.title} - Episodes[/bold white]\n")
        
        # Get TV Series details to fetch seasons/episodes
        try:
            from moviebox_api.core import TVSeriesDetails
            from moviebox_api.helpers import get_event_loop
            
            console.print("[yellow]Fetching series information...[/yellow]")
            
            # Get series details - use get_json_details_extractor_model to get full structure
            details = TVSeriesDetails(item, self.session)
            json_model = get_event_loop().run_until_complete(details.get_json_details_extractor_model())
            
            # DEBUG
            console.print(f"[dim]DEBUG: json_model has resource? {hasattr(json_model, 'resource')}[/dim]")
            
            if hasattr(json_model, 'resource'):
                console.print(f"[dim]DEBUG: resource has seasons? {hasattr(json_model.resource, 'seasons')}[/dim]")
                if hasattr(json_model.resource, 'seasons'):
                    console.print(f"[dim]DEBUG: seasons count = {len(json_model.resource.seasons)}[/dim]")
            
            # Access resource.seasons directly! (NOT resData.resource.seasons)
            console.print(f"\n[bold cyan]Available Seasons:[/bold cyan]")
            
            seasons_list = []
            if hasattr(json_model, 'resource') and hasattr(json_model.resource, 'seasons'):
                seasons_list = json_model.resource.seasons
            
            if seasons_list:
                seasons_table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
                seasons_table.add_column("Season", style="cyan bold", width=15)
                seasons_table.add_column("Episodes", style="white")
                
                for season in seasons_list:
                    # Season model has 'se' for season number, 'maxEp' for episode count
                    season_num = season.se if hasattr(season, 'se') else 0
                    max_ep = season.maxEp if hasattr(season, 'maxEp') else 0
                    seasons_table.add_row(
                        f"Season {season_num}",
                        f"{max_ep} episodes"
                    )
                
                console.print(seasons_table)
            else:
                console.print("[yellow]Season information not available[/yellow]")
            
            # Ask for season
            season_num = Prompt.ask(
                "\n[bold cyan]Enter season number[/bold cyan]",
                default="1"
            )
            season_num = int(season_num)
            
            # Find matching season from seasons list
            selected_season = None
            if seasons_list:
                for season in seasons_list:
                    if hasattr(season, 'se') and season.se == season_num:
                        selected_season = season
                        break
            
            if not selected_season:
                console.print(f"\n[red]Season {season_num} not found![/red]")
                console.input("\nPress Enter to continue...")
                return
            
            # Episodes: generate from 1 to maxEp
            max_episodes = selected_season.maxEp if hasattr(selected_season, 'maxEp') else 0
            
            if max_episodes == 0:
                console.print(f"\n[yellow]No episodes found for season {season_num}[/yellow]")
                console.input("\nPress Enter to continue...")
                return
            
            # Display episodes for selected season
            console.clear()
            self.show_header()
            
            console.print(f"\n[bold white]{item.title} - Season {season_num}[/bold white]")
            console.print(f"[dim]{max_episodes} episodes available[/dim]\n")
            
            # Episodes table - generate from 1 to maxEp
            episodes_table = Table(
                show_header=True,
                header_style="bold cyan",
                box=box.ROUNDED,
                padding=(0, 1)
            )
            
            episodes_table.add_column("#", style="dim", width=4)
            episodes_table.add_column("Episode", style="cyan", width=10)
            episodes_table.add_column("Title", style="bold white", no_wrap=False)
            
            for ep_num in range(1, max_episodes + 1):
                episodes_table.add_row(
                    str(ep_num),
                    f"E{ep_num}",
                    f"Episode {ep_num}"
                )
            
            console.print(episodes_table)
            
            # Options
            console.print("\n[bold]Options:[/bold]")
            console.print(f"[cyan]1-{max_episodes}[/cyan] Select episode to stream/download")
            console.print("[cyan]0[/cyan] Back")
            
            choice = Prompt.ask("\n[bold cyan]Choose[/bold cyan]")
            
            if choice == "0":
                return
            elif choice.isdigit() and 1 <= int(choice) <= max_episodes:
                # Get selected episode number
                ep_num = int(choice)
                
                # Show episode actions
                console.print(f"\n[bold]Episode {ep_num} - Actions:[/bold]")
                action_table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
                action_table.add_column("Option", style="cyan bold", width=8)
                action_table.add_column("Description", style="white")
                
                action_table.add_row("1", "▶️  Stream Episode")
                action_table.add_row("2", "⬇️  Download Episode")
                action_table.add_row("0", "← Back")
                
                console.print(action_table)
                
                action = Prompt.ask("\n[bold cyan]Action[/bold cyan]", choices=["0", "1", "2"], default="1")
                
                if action == "1":
                    # Stream episode with proper season/episode info
                    self.stream_episode(item, season_num, ep_num)
                elif action == "2":
                    # Download episode
                    self.download_episode(item, season_num, ep_num)
            else:
                console.print("[red]Invalid choice![/red]")
                console.input("\nPress Enter to continue...")
        
        except Exception as e:
            console.print(f"\n[red]❌ Error fetching episodes: {e}[/red]")
            console.print("[dim]Falling back to manual input...[/dim]\n")
            
            # Fallback: manual season/episode input
            season = int(Prompt.ask("[bold cyan]Season number[/bold cyan]", default="1"))
            episode = int(Prompt.ask("[bold cyan]Episode number[/bold cyan]", default="1"))
            
            console.print("\n[bold]Actions:[/bold]")
            console.print("[cyan]1[/cyan] Stream")
            console.print("[cyan]2[/cyan] Download")
            console.print("[cyan]0[/cyan] Back")
            
            action = Prompt.ask("\n[bold cyan]Action[/bold cyan]", choices=["0", "1", "2"], default="1")
            
            if action == "1":
                self.stream_episode(item, season, episode)
            elif action == "2":
                self.download_episode(item, season, episode)
        
        console.input("\nPress Enter to continue...")
    
    def stream_episode(self, item, season, episode):
        """Stream a specific TV episode"""
        console.print(f"\n[bold yellow]🎬 Streaming: {item.title} S{season}E{episode}[/bold yellow]\n")
        
        quality = self.get_quality_selection()
        want_subs, languages = self.get_subtitle_preferences_from_api(item)
        
        # Check and select player
        import shutil
        available_players = [p for p in ["mpv", "vlc", "mplayer"] if shutil.which(p)]
        
        if not available_players:
            console.print("\n[red]❌ No media player found[/red]")
            return
        
        player = available_players[0] if len(available_players) == 1 else self.select_player(available_players)
        
        console.print(f"\n[green]✓ Using {player.upper()} player[/green]")
        console.print(f"[green]✓ Quality: {quality}[/green]")
        if want_subs:
            console.print(f"[green]✓ Subtitles: {languages[0]}[/green]")
        
        try:
            from moviebox_api.cli.downloader import Downloader
            from moviebox_api.helpers import get_event_loop
            
            console.print(f"\n[bold yellow]Streaming: {item.title} S{season}E{episode}[/bold yellow]\n")
            
            downloader = Downloader()
            get_event_loop().run_until_complete(
                downloader.download_tv_series(
                    item.title,
                    year=item.releaseDate.year,
                    season=season,
                    episode=episode,
                    yes=True,
                    quality=quality,
                    language=languages if want_subs else [],
                    download_caption=want_subs,
                    stream_via=player,
                    limit=1
                )
            )
        except KeyboardInterrupt:
            console.print("\n\n[yellow]Streaming stopped[/yellow]")
        except Exception as e:
            console.print(f"\n[red]❌ Error: {e}[/red]")
    
    def download_episode(self, item, season, episode):
        """Download a specific TV episode"""
        console.print(f"\n[bold yellow]⬇️  Downloading: {item.title} S{season}E{episode}[/bold yellow]\n")
        
        quality = self.get_quality_selection()
        download_subs, languages = self.get_subtitle_preferences_from_api(item)
        
        console.print("\n[bold]Download Settings:[/bold]")
        console.print(f"[green]✓ Quality: {quality}[/green]")
        console.print(f"[green]✓ Subtitles: {languages[0] if download_subs else 'Disabled'}[/green]")
        
        if not Confirm.ask("\n[bold cyan]Start download?[/bold cyan]", default=True):
            return
        
        try:
            from moviebox_api.cli.downloader import Downloader
            from moviebox_api.helpers import get_event_loop
            
            console.print("\n[yellow]Starting download...[/yellow]\n")
            
            downloader = Downloader()
            get_event_loop().run_until_complete(
                downloader.download_tv_series(
                    item.title,
                    year=item.releaseDate.year,
                    season=season,
                    episode=episode,
                    yes=True,
                    quality=quality,
                    language=languages if download_subs else [],
                    download_caption=download_subs,
                    limit=1
                )
            )
            
            console.print("\n[bold green]✓ Download complete![/bold green]")
        except Exception as e:
            console.print(f"\n[red]❌ Error: {e}[/red]")
    
    def get_subtitle_preferences_from_api(self, item):
        """Get subtitle preferences with available languages from API"""
        want_subs = Confirm.ask("\n[bold cyan]Enable subtitles?[/bold cyan]", default=True)
        
        if not want_subs:
            return False, []
        
        # Try to fetch available subtitles from item
        available_languages = []
        
        try:
            # Check if item has subtitle information
            if hasattr(item, 'subtitles') and item.subtitles:
                available_languages = list(item.subtitles.keys())
            elif hasattr(item, 'captions') and item.captions:
                available_languages = [cap.language for cap in item.captions if hasattr(cap, 'language')]
        except:
            pass
        
        # Fallback to common languages if no API data
        if not available_languages:
            available_languages = ["Indonesian", "English", "Spanish", "French", "Chinese", "Japanese", "Korean", "Arabic", "Portuguese", "Russian"]
        
        console.print(f"\n[bold]Subtitle Languages:[/bold] [dim]({len(available_languages)} available)[/dim]")
        
        # Show in table format
        table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
        table.add_column("Option", style="cyan bold", width=8)
        table.add_column("Language", style="white")
        
        # Show up to 10 languages, then "More..."
        display_langs = available_languages[:10]
        for idx, lang in enumerate(display_langs, 1):
            flag = self.get_language_flag(lang)
            table.add_row(str(idx), f"{flag} {lang}")
        
        if len(available_languages) > 10:
            table.add_row("11", f"... and {len(available_languages) - 10} more")
        
        table.add_row("0", "Custom (type manually)")
        
        console.print(table)
        
        choices = [str(i) for i in range(len(display_langs) + 1)] + ["0"]
        if len(available_languages) > 10:
            choices.append("11")
        
        choice = Prompt.ask(
            f"[bold cyan]Language[/bold cyan] [dim](1-{len(display_langs)})[/dim]",
            default="1"
        )
        
        if choice == "0":
            custom_lang = Prompt.ask("[bold cyan]Enter language name[/bold cyan]")
            return True, [custom_lang]
        elif choice == "11" and len(available_languages) > 10:
            # Show all languages
            console.print("\n[bold]All Available Languages:[/bold]")
            for idx, lang in enumerate(available_languages, 1):
                console.print(f"[cyan]{idx:2}[/cyan] {lang}")
            
            choice = Prompt.ask(
                f"\n[bold cyan]Select language number[/bold cyan] [dim](1-{len(available_languages)})[/dim]"
            )
            
            if choice.isdigit() and 1 <= int(choice) <= len(available_languages):
                return True, [available_languages[int(choice) - 1]]
            else:
                return True, [available_languages[0]]  # default to first
        elif choice.isdigit() and 1 <= int(choice) <= len(display_langs):
            return True, [available_languages[int(choice) - 1]]
        else:
            return True, [available_languages[0]]  # default to first
    
    def get_language_flag(self, language):
        """Get emoji flag for language"""
        flags = {
            "Indonesian": "🇮🇩",
            "English": "🇬🇧",
            "Spanish": "🇪🇸",
            "French": "🇫🇷",
            "Chinese": "🇨🇳",
            "Japanese": "🇯🇵",
            "Korean": "🇰🇷",
            "Arabic": "🇸🇦",
            "Portuguese": "🇵🇹",
            "Russian": "🇷🇺",
            "German": "🇩🇪",
            "Italian": "🇮🇹"
        }
        return flags.get(language, "🌐")
    
    def select_player(self, available_players):
        """Select media player from available options"""
        console.print("\n[bold]Available Players:[/bold]")
        for p in available_players:
            console.print(f"[green]✓ {p.upper()}[/green]")
        
        console.print("\n[bold]Select Player:[/bold]")
        for idx, p in enumerate(available_players, 1):
            console.print(f"[cyan]{idx}[/cyan] {p.upper()}")
        
        player_choice = Prompt.ask(
            "[bold cyan]Player[/bold cyan]",
            choices=[str(i) for i in range(1, len(available_players) + 1)],
            default="1"
        )
        return available_players[int(player_choice) - 1]
    
    def run(self):
        """Main TUI loop"""
        try:
            while True:
                console.clear()
                self.show_header()
                
                choice = self.show_main_menu()
                
                if choice == "0":
                    console.print("\n[bold cyan]👋 Goodbye![/bold cyan]\n")
                    break
                elif choice == "1":
                    self.search_content(SubjectType.MOVIES)
                elif choice == "2":
                    self.search_content(SubjectType.TV_SERIES)
                elif choice == "3":
                    self.search_content(SubjectType.ALL)
                elif choice == "4":
                    console.print("\n[yellow]Trending feature coming soon![/yellow]")
                    console.input("\nPress Enter to continue...")
                
        except KeyboardInterrupt:
            console.print("\n\n[bold cyan]👋 Goodbye![/bold cyan]\n")
        except Exception as e:
            console.print(f"\n[bold red]❌ Error: {e}[/bold red]\n")
            sys.exit(1)


def run_interactive_menu():
    """Entry point for interactive TUI"""
    app = MovieBoxTUI()
    app.run()


if __name__ == "__main__":
    run_interactive_menu()

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../services/auth_service.dart';

class FeedScreen extends ConsumerWidget {
  const FeedScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final authAsync = ref.watch(authNotifierProvider);
    final user = authAsync.value;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Лента'),
        actions: [
          IconButton(
            icon: const Icon(Icons.notifications_outlined),
            onPressed: () {},
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (user != null) ...[
            _GreetingCard(
              username: user.username,
              isPilot: user.isPilot,
              isManager: user.isManager,
            ),
            const SizedBox(height: 20),
          ],
          const _SectionHeader('Последние результаты'),
          const SizedBox(height: 12),
          // Заглушка — будет заменена на данные из API
          ...List.generate(5, (i) => _ResultCard(index: i)),
        ],
      ),
    );
  }
}

class _GreetingCard extends StatelessWidget {
  final String username;
  final bool isPilot;
  final bool isManager;

  const _GreetingCard({
    required this.username,
    required this.isPilot,
    required this.isManager,
  });

  @override
  Widget build(BuildContext context) {
    String subtitle;
    IconData icon;
    Color color;

    if (isPilot) {
      subtitle = 'Профиль пилота';
      icon = Icons.sports_motorsports;
      color = const Color(0xFFE94560);
    } else if (isManager) {
      subtitle = 'Менеджер команды';
      icon = Icons.groups;
      color = const Color(0xFF0F3460);
    } else {
      subtitle = 'Болельщик';
      icon = Icons.favorite_outline;
      color = const Color(0xFF533483);
    }

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: [color.withOpacity(0.3), color.withOpacity(0.05)],
          begin: Alignment.centerLeft,
          end: Alignment.centerRight,
        ),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: color.withOpacity(0.3)),
      ),
      child: Row(
        children: [
          Icon(icon, color: color, size: 32),
          const SizedBox(width: 14),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Привет, $username!', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16)),
              Text(subtitle, style: TextStyle(color: Colors.grey[400], fontSize: 13)),
            ],
          ),
        ],
      ),
    );
  }
}

class _SectionHeader extends StatelessWidget {
  final String title;
  const _SectionHeader(this.title);

  @override
  Widget build(BuildContext context) {
    return Text(
      title,
      style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16),
    );
  }
}

class _ResultCard extends StatelessWidget {
  final int index;
  const _ResultCard({required this.index});

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor: const Color(0xFFE94560).withOpacity(0.2),
          child: Text('${index + 1}', style: const TextStyle(color: Color(0xFFE94560), fontWeight: FontWeight.bold)),
        ),
        title: Text('Этап ${index + 1} — Класс Junior', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w500)),
        subtitle: Text('15 июня 2026', style: TextStyle(color: Colors.grey[500], fontSize: 12)),
        trailing: const Icon(Icons.chevron_right, color: Colors.grey),
        onTap: () {},
      ),
    );
  }
}
